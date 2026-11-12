use std::collections::{HashMap, HashSet};
use std::fs;
use chrono::{DateTime, Local};
use rusqlite::{params, Connection};
use serde_json::Value;

use crate::config::{get_data_root, get_db_path, load_config};
use crate::models::{
    AccountStatus, Counts, DashboardData, PublishedClip, QueueClip, ReadyClip, ScheduledClip,
    StreamerConfig,
};

pub fn open_connection() -> Result<Connection, String> {
    let db_path = get_db_path();
    if let Some(parent) = db_path.parent() {
        fs::create_dir_all(parent).map_err(|e| format!("DB dir error: {}", e))?;
    }
    let conn = Connection::open(&db_path).map_err(|e| format!("DB Open error: {}", e))?;
    conn.execute_batch(
        "PRAGMA journal_mode = WAL;
         PRAGMA synchronous = NORMAL;
         PRAGMA busy_timeout = 5000;",
    )
    .map_err(|e| format!("DB PRAGMA error: {}", e))?;
    init_db(&conn)?;
    Ok(conn)
}

pub fn init_db(conn: &Connection) -> Result<(), String> {
    conn.execute_batch(
        r#"
        CREATE TABLE IF NOT EXISTS clips (
            clip_id TEXT PRIMARY KEY,
            streamer TEXT NOT NULL,
            platform TEXT DEFAULT 'twitch',
            original_title TEXT,
            url TEXT,
            view_count INTEGER,
            duration REAL,
            clip_created_at TEXT,
            harvested_at TEXT,
            status TEXT DEFAULT 'harvested',
            raw_path TEXT,
            short_path TEXT,
            ai_title TEXT,
            ai_description TEXT,
            ai_tags TEXT,
            error_msg TEXT,
            scheduled_publish_at TEXT,
            published_at TEXT,
            youtube_video_id TEXT,
            tiktok_publish_id TEXT,
            is_manually_published INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS streamer_checks (
            streamer TEXT PRIMARY KEY,
            last_checked_at TEXT,
            clips_found INTEGER DEFAULT 0
        );
        "#,
    )
    .map_err(|e| format!("DB init error: {}", e))?;

    let mut existing_cols: HashSet<String> = HashSet::new();
    {
        let mut stmt = conn
            .prepare("PRAGMA table_info(clips)")
            .map_err(|e| e.to_string())?;
        let rows = stmt
            .query_map([], |row| row.get::<_, String>(1))
            .map_err(|e| e.to_string())?;
        for col in rows.flatten() {
            existing_cols.insert(col);
        }
    }
    if !existing_cols.contains("scheduled_publish_at") {
        let _ = conn.execute("ALTER TABLE clips ADD COLUMN scheduled_publish_at TEXT", []);
    }
    if !existing_cols.contains("is_manually_published") {
        let _ = conn.execute(
            "ALTER TABLE clips ADD COLUMN is_manually_published INTEGER DEFAULT 0",
            [],
        );
    }
    let _ = conn.execute("PRAGMA user_version = 1", []);
    Ok(())
}

pub fn format_relative_time(iso_ts: Option<&str>) -> (String, String) {
    let ts_str = match iso_ts {
        Some(s) if !s.trim().is_empty() => s.trim(),
        _ => return ("-".to_string(), "".to_string()),
    };

    let dt = match DateTime::parse_from_rfc3339(&ts_str.replace("Z", "+00:00")) {
        Ok(parsed) => parsed.with_timezone(&Local),
        Err(_) => match chrono::NaiveDateTime::parse_from_str(ts_str, "%Y-%m-%d %H:%M:%S") {
            Ok(naive) => naive.and_local_timezone(Local).unwrap(),
            Err(_) => return (ts_str.to_string(), ts_str.to_string()),
        },
    };

    let now = Local::now();
    let diff = now.signed_duration_since(dt);
    let full_str = dt.format("%d.%m.%Y %H:%M Uhr").to_string();

    let diff_secs = diff.num_seconds();
    if diff_secs < 60 {
        ("Gerade eben".to_string(), full_str)
    } else if diff_secs < 3600 {
        (format!("Vor {} Min.", diff_secs / 60), full_str)
    } else if diff_secs < 86400 {
        (format!("Vor {} Std.", diff_secs / 3600), full_str)
    } else if diff_secs < 86400 * 2 {
        (format!("Gestern {}", dt.format("%H:%M")), full_str)
    } else {
        (format!("Vor {} Tagen", diff_secs / 86400), full_str)
    }
}

pub fn fetch_dashboard_data() -> Result<DashboardData, String> {
    let base_dir = get_data_root();
    let conn = open_connection()?;

    // 1. Counts
    let mut stmt = conn
        .prepare("SELECT status, COUNT(*) FROM clips GROUP BY status")
        .map_err(|e| e.to_string())?;

    let mut raw_counts: HashMap<String, i64> = HashMap::new();
    let count_rows = stmt
        .query_map([], |row| {
            let status: String = row.get(0)?;
            let count: i64 = row.get(1)?;
            Ok((status, count))
        })
        .map_err(|e| e.to_string())?;

    for r in count_rows.flatten() {
        raw_counts.insert(r.0, r.1);
    }

    let harvested_count = *raw_counts.get("harvested").unwrap_or(&0);
    let ready_count = *raw_counts.get("ready").unwrap_or(&0) + *raw_counts.get("completed").unwrap_or(&0);
    let scheduled_count = *raw_counts.get("scheduled").unwrap_or(&0);
    let published_count = *raw_counts.get("published").unwrap_or(&0);

    let counts = Counts {
        harvested: harvested_count,
        ready: ready_count,
        scheduled: scheduled_count,
        published: published_count,
    };

    // 2. Queue Clips
    let mut q_stmt = conn
        .prepare("SELECT clip_id, streamer, original_title, view_count, duration, clip_created_at, harvested_at FROM clips WHERE status = 'harvested' ORDER BY view_count DESC")
        .map_err(|e| e.to_string())?;

    let today_local = Local::now().date_naive();
    let mut queue_clips = Vec::new();
    let mut older_queue_count = 0;

    let q_rows = q_stmt
        .query_map([], |row| {
            let clip_id: String = row.get(0)?;
            let streamer: String = row.get(1)?;
            let original_title: String = row.get(2).unwrap_or_default();
            let view_count: i64 = row.get(3).unwrap_or(0);
            let duration: f64 = row.get(4).unwrap_or(0.0);
            let clip_created_at: Option<String> = row.get(5)?;
            let harvested_at: Option<String> = row.get(6)?;
            Ok((
                clip_id,
                streamer,
                original_title,
                view_count,
                duration,
                clip_created_at,
                harvested_at,
            ))
        })
        .map_err(|e| e.to_string())?;

    for r in q_rows.flatten() {
        let ts_ref = r.5.as_deref().or(r.6.as_deref());
        let (ago, full) = format_relative_time(ts_ref);

        if let Some(ts) = ts_ref {
            if let Ok(parsed) = DateTime::parse_from_rfc3339(&ts.replace("Z", "+00:00")) {
                if parsed.with_timezone(&Local).date_naive() < today_local {
                    older_queue_count += 1;
                }
            } else {
                older_queue_count += 1;
            }
        } else {
            older_queue_count += 1;
        }

        queue_clips.push(QueueClip {
            clip_id: r.0,
            streamer: r.1,
            original_title: r.2,
            view_count: r.3,
            duration: r.4,
            clip_created_at: r.5,
            harvested_at: r.6,
            created_ago: ago,
            created_full: full,
        });
    }

    // 3. Ready Clips (Studio)
    let mut r_stmt = conn
        .prepare("SELECT clip_id, streamer, original_title, ai_title, view_count, is_manually_published, clip_created_at, harvested_at FROM clips WHERE status IN ('ready', 'completed') ORDER BY LOWER(streamer) ASC, rowid DESC")
        .map_err(|e| e.to_string())?;

    let mut ready_clips = Vec::new();
    let mut streamer_counts: HashMap<String, usize> = HashMap::new();

    let meta_dir = base_dir.join("output").join("metadata");
    let shorts_dir = base_dir.join("output").join("shorts");
    let raw_dir = base_dir.join("downloads").join("raw");

    let r_rows = r_stmt
        .query_map([], |row| {
            let clip_id: String = row.get(0)?;
            let streamer: String = row.get(1)?;
            let orig_title: String = row.get(2).unwrap_or_default();
            let ai_title: Option<String> = row.get(3)?;
            let view_count: i64 = row.get(4).unwrap_or(0);
            let is_man_pub: Option<i64> = row.get(5)?;
            let clip_created_at: Option<String> = row.get(6)?;
            let harvested_at: Option<String> = row.get(7)?;
            Ok((
                clip_id,
                streamer,
                orig_title,
                ai_title,
                view_count,
                is_man_pub.unwrap_or(0) != 0,
                clip_created_at,
                harvested_at,
            ))
        })
        .map_err(|e| e.to_string())?;

    for r in r_rows.flatten() {
        let clip_id = r.0;
        let streamer = r.1;
        let orig_title = r.2;
        let ai_title = r.3;
        let view_count = r.4;
        let mut is_manually_published = r.5;

        let mut title = ai_title.unwrap_or_else(|| orig_title.clone());
        let mut sticker_text = orig_title.clone();
        let mut sub_position = "bottom".to_string();
        let mut layout_mode = "auto".to_string();
        let mut cam_filter = "none".to_string();

        let meta_file = meta_dir.join(format!("{}.json", clip_id));
        if meta_file.exists() {
            if let Ok(meta_raw) = fs::read_to_string(&meta_file) {
                if let Ok(v) = serde_json::from_str::<Value>(&meta_raw) {
                    if let Some(st) = v.get("sticker_text").and_then(|s| s.as_str()) {
                        sticker_text = st.to_string();
                    }
                    if let Some(sp) = v.get("sub_position").and_then(|s| s.as_str()) {
                        sub_position = sp.to_string();
                    }
                    if let Some(lm) = v.get("layout_mode").and_then(|s| s.as_str()) {
                        layout_mode = lm.to_string();
                    }
                    if let Some(cf) = v.get("cam_filter").and_then(|s| s.as_str()) {
                        cam_filter = cf.to_string();
                    }
                    if let Some(imp) = v.get("is_manually_published").and_then(|s| s.as_bool()) {
                        is_manually_published = imp;
                    }
                    if let Some(t) = v.get("title").and_then(|s| s.as_str()) {
                        if !t.is_empty() {
                            title = t.to_string();
                        }
                    }
                }
            }
        }

        let txt_path = raw_dir.join(format!("{}_transcript.txt", clip_id));
        let transcript = fs::read_to_string(&txt_path).unwrap_or_default();
        let short_file = shorts_dir.join(format!("short_{}.mp4", clip_id));
        let thumb_file = base_dir.join("data").join("thumbnails").join(format!("{}.jpg", clip_id));
        let has_video = short_file.exists();
        let updated_at = if thumb_file.exists() {
            thumb_file.metadata().ok().and_then(|m| m.modified().ok()).and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok()).map(|d| d.as_secs() as i64).unwrap_or(0)
        } else if short_file.exists() {
            short_file.metadata().ok().and_then(|m| m.modified().ok()).and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok()).map(|d| d.as_secs() as i64).unwrap_or(0)
        } else {
            0
        };

        let (ago, full) = format_relative_time(r.6.as_deref().or(r.7.as_deref()));

        let st_key = streamer.to_lowercase();
        *streamer_counts.entry(st_key).or_insert(0) += 1;

        ready_clips.push(ReadyClip {
            clip_id,
            streamer,
            title,
            sticker_text,
            sub_position,
            transcript,
            view_count,
            layout_mode,
            cam_filter,
            is_manually_published,
            has_video,
            updated_at,
            created_ago: ago,
            created_full: full,
        });
    }

    // 4. Scheduled Clips
    let mut s_stmt = conn
        .prepare("SELECT clip_id, streamer, original_title, ai_title, scheduled_publish_at, view_count FROM clips WHERE status = 'scheduled' ORDER BY scheduled_publish_at ASC")
        .map_err(|e| e.to_string())?;

    let mut scheduled_clips = Vec::new();
    let s_rows = s_stmt
        .query_map([], |row| {
            Ok(ScheduledClip {
                clip_id: row.get(0)?,
                streamer: row.get(1)?,
                original_title: row.get(2).unwrap_or_default(),
                ai_title: row.get(3)?,
                scheduled_publish_at: row.get(4)?,
                view_count: row.get(5).unwrap_or(0),
            })
        })
        .map_err(|e| e.to_string())?;

    for sc in s_rows.flatten() {
        scheduled_clips.push(sc);
    }

    // 5. Published Clips
    let mut p_stmt = conn
        .prepare("SELECT clip_id, streamer, original_title, ai_title, published_at, youtube_video_id, tiktok_publish_id FROM clips WHERE status = 'published' ORDER BY rowid DESC")
        .map_err(|e| e.to_string())?;

    let mut published_clips = Vec::new();
    let p_rows = p_stmt
        .query_map([], |row| {
            Ok(PublishedClip {
                clip_id: row.get(0)?,
                streamer: row.get(1)?,
                original_title: row.get(2).unwrap_or_default(),
                ai_title: row.get(3)?,
                published_at: row.get(4)?,
                youtube_video_id: row.get(5)?,
                tiktok_publish_id: row.get(6)?,
            })
        })
        .map_err(|e| e.to_string())?;

    for pc in p_rows.flatten() {
        published_clips.push(pc);
    }

    // 6. Streamers from config.yaml
    let avatar_cache_path = base_dir.join("data").join("streamer_avatars.json");
    let avatar_cache: HashMap<String, Value> = if avatar_cache_path.exists() {
        fs::read_to_string(&avatar_cache_path)
            .ok()
            .and_then(|c| serde_json::from_str(&c).ok())
            .unwrap_or_default()
    } else {
        HashMap::new()
    };

    let app_cfg = load_config();
    let mut streamers = Vec::new();
    for item in app_cfg.streamers {
        let clean_login = item.name.to_lowercase();
        let av_entry = avatar_cache.get(&clean_login);
        let avatar_url = av_entry
            .and_then(|v| v.get("avatar_url"))
            .and_then(|v| v.as_str())
            .map(|s| s.to_string());
        let display_name = av_entry
            .and_then(|v| v.get("display_name"))
            .and_then(|v| v.as_str())
            .map(|s| s.to_string());
        let has_custom_crops = Some(item.custom_crops.is_some());

        streamers.push(StreamerConfig {
            name: item.name,
            platform: item.platform,
            enabled: item.enabled,
            min_clip_views: item.min_clip_views,
            max_clips_per_run: item.max_clips_per_run,
            layout: item.layout,
            avatar_url,
            display_name,
            has_custom_crops,
        });
    }

    // 7. Account Status (Upload/Account-Verknüpfung dauerhaft entfernt)
    let account_status = AccountStatus {
        youtube_connected: false,
        youtube_channel: "Nicht verknüpft".to_string(),
        tiktok_connected: false,
        tiktok_user: "Nicht verknüpft".to_string(),
    };

    Ok(DashboardData {
        counts,
        older_queue_count,
        queue_clips,
        ready_clips,
        scheduled_clips,
        published_clips,
        streamers,
        streamer_counts,
        account_status,
    })
}

#[derive(Debug, Clone)]
pub struct ClipRecord {
    pub clip_id: String,
    pub streamer: String,
    pub original_title: String,
    pub url: String,
    pub view_count: i64,
    pub duration: f64,
    pub status: String,
    pub raw_path: Option<String>,
    pub short_path: Option<String>,
    pub ai_title: Option<String>,
}

pub fn get_clip_by_id(clip_id: &str) -> Result<Option<ClipRecord>, String> {
    let conn = open_connection()?;
    let mut stmt = conn
        .prepare("SELECT clip_id, streamer, original_title, url, view_count, duration, status, raw_path, short_path, ai_title FROM clips WHERE clip_id = ?1")
        .map_err(|e| e.to_string())?;
    let mut rows = stmt
        .query_map([clip_id], |row| {
            Ok(ClipRecord {
                clip_id: row.get(0)?,
                streamer: row.get(1)?,
                original_title: row.get::<_, Option<String>>(2)?.unwrap_or_default(),
                url: row.get::<_, Option<String>>(3)?.unwrap_or_default(),
                view_count: row.get::<_, Option<i64>>(4)?.unwrap_or(0),
                duration: row.get::<_, Option<f64>>(5)?.unwrap_or(30.0),
                status: row.get::<_, Option<String>>(6)?.unwrap_or_else(|| "harvested".to_string()),
                raw_path: row.get(7)?,
                short_path: row.get(8)?,
                ai_title: row.get(9)?,
            })
        })
        .map_err(|e| e.to_string())?;
    if let Some(r) = rows.next() {
        return r.map(Some).map_err(|e| e.to_string());
    }
    Ok(None)
}

pub fn get_pending_clips() -> Result<Vec<ClipRecord>, String> {
    let conn = open_connection()?;
    let mut stmt = conn
        .prepare("SELECT clip_id, streamer, original_title, url, view_count, duration, status, raw_path, short_path, ai_title FROM clips WHERE status = 'harvested' ORDER BY view_count DESC")
        .map_err(|e| e.to_string())?;
    let rows = stmt
        .query_map([], |row| {
            Ok(ClipRecord {
                clip_id: row.get(0)?,
                streamer: row.get(1)?,
                original_title: row.get::<_, Option<String>>(2)?.unwrap_or_default(),
                url: row.get::<_, Option<String>>(3)?.unwrap_or_default(),
                view_count: row.get::<_, Option<i64>>(4)?.unwrap_or(0),
                duration: row.get::<_, Option<f64>>(5)?.unwrap_or(30.0),
                status: row.get::<_, Option<String>>(6)?.unwrap_or_else(|| "harvested".to_string()),
                raw_path: row.get(7)?,
                short_path: row.get(8)?,
                ai_title: row.get(9)?,
            })
        })
        .map_err(|e| e.to_string())?;
    Ok(rows.flatten().collect())
}

pub fn update_clip_status(clip_id: &str, status: &str) -> Result<(), String> {
    let conn = open_connection()?;
    conn.execute(
        "UPDATE clips SET status = ?1 WHERE clip_id = ?2",
        params![status, clip_id],
    )
    .map_err(|e| e.to_string())?;
    Ok(())
}

pub fn update_clip_rendered(clip_id: &str, short_path: &str, ai_title: Option<&str>) -> Result<(), String> {
    let conn = open_connection()?;
    if let Some(title) = ai_title {
        conn.execute(
            "UPDATE clips SET status = 'ready', short_path = ?1, ai_title = ?2, error_msg = NULL WHERE clip_id = ?3",
            params![short_path, title, clip_id],
        )
        .map_err(|e| e.to_string())?;
    } else {
        conn.execute(
            "UPDATE clips SET status = 'ready', short_path = ?1, error_msg = NULL WHERE clip_id = ?2",
            params![short_path, clip_id],
        )
        .map_err(|e| e.to_string())?;
    }
    Ok(())
}

pub fn update_clip_error(clip_id: &str, err_msg: &str) -> Result<(), String> {
    let conn = open_connection()?;
    conn.execute(
        "UPDATE clips SET status = 'failed', error_msg = ?1 WHERE clip_id = ?2",
        params![err_msg, clip_id],
    )
    .map_err(|e| e.to_string())?;
    Ok(())
}

pub fn toggle_manually_published(clip_id: &str) -> Result<bool, String> {
    let conn = open_connection()?;
    let cur: i64 = conn
        .query_row(
            "SELECT COALESCE(is_manually_published, 0) FROM clips WHERE clip_id = ?1",
            [clip_id],
            |row| row.get(0),
        )
        .unwrap_or(0);
    let next = if cur == 0 { 1 } else { 0 };
    conn.execute(
        "UPDATE clips SET is_manually_published = ?1 WHERE clip_id = ?2",
        params![next, clip_id],
    )
    .map_err(|e| e.to_string())?;
    Ok(next == 1)
}

pub fn get_processed_ids(clip_ids: &[String]) -> Result<HashSet<String>, String> {
    if clip_ids.is_empty() {
        return Ok(HashSet::new());
    }
    let conn = open_connection()?;
    let mut out = HashSet::new();
    for chunk in clip_ids.chunks(500) {
        let placeholders = vec!["?"; chunk.len()].join(",");
        let sql = format!("SELECT clip_id FROM clips WHERE clip_id IN ({})", placeholders);
        let mut stmt = conn.prepare(&sql).map_err(|e| e.to_string())?;
        let params_refs: Vec<&dyn rusqlite::ToSql> = chunk.iter().map(|s| s as &dyn rusqlite::ToSql).collect();
        let rows = stmt
            .query_map(params_refs.as_slice(), |row| row.get::<_, String>(0))
            .map_err(|e| e.to_string())?;
        for r in rows.flatten() {
            out.insert(r);
        }
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_db_init_insert_and_fetch_dashboard_isolated() {
        let tmp = std::env::temp_dir().join(format!("cf_db_test_{}", std::process::id()));
        let _ = fs::remove_dir_all(&tmp);
        fs::create_dir_all(&tmp).unwrap();
        unsafe {
            std::env::set_var("CLIP_FARMING_DATA_DIR", &tmp);
        }

        let conn = open_connection().unwrap();
        conn.execute(
            "INSERT INTO clips (clip_id, streamer, original_title, view_count, duration, status) VALUES ('c1', 'trymacs', 'Test Clip', 150, 25.0, 'harvested')",
            [],
        )
        .unwrap();
        drop(conn);

        let dash = fetch_dashboard_data().unwrap();
        assert_eq!(dash.counts.harvested, 1);
        assert_eq!(dash.queue_clips.len(), 1);
        assert_eq!(dash.queue_clips[0].clip_id, "c1");

        assert!(toggle_manually_published("c1").unwrap());
        assert!(!toggle_manually_published("c1").unwrap());

        unsafe {
            std::env::remove_var("CLIP_FARMING_DATA_DIR");
        }
        let _ = fs::remove_dir_all(&tmp);
    }
}
