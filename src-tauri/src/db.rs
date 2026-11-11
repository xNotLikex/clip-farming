use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};
use chrono::{DateTime, Local};
use rusqlite::Connection;
use serde_json::Value;

use crate::models::{
    AccountStatus, Counts, DashboardData, PublishedClip, QueueClip, ReadyClip, ScheduledClip,
    StreamerConfig,
};

fn get_base_dir() -> PathBuf {
    if let Ok(exe_path) = std::env::current_exe() {
        if let Some(exe_dir) = exe_path.parent() {
            if exe_dir.join("data").exists() {
                return exe_dir.to_path_buf();
            }
            if let Some(parent) = exe_dir.parent() {
                if parent.join("data").exists() {
                    return parent.to_path_buf();
                }
            }
        }
    }
    if Path::new("data").exists() {
        PathBuf::from(".")
    } else if Path::new("../data").exists() {
        PathBuf::from("..")
    } else {
        PathBuf::from(".")
    }
}

fn get_db_path() -> PathBuf {
    let base = get_base_dir();
    let p = base.join("data").join("pipeline.db");
    if p.exists() {
        return p;
    }
    let alt = PathBuf::from("../data/pipeline.db");
    if alt.exists() {
        return alt;
    }
    p
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
    let base_dir = get_base_dir();
    let db_path = get_db_path();

    let conn = Connection::open(&db_path).map_err(|e| format!("DB Open error: {}", e))?;

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
        let has_video = short_file.exists();

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
        .prepare("SELECT clip_id, streamer, original_title, ai_title, published_at, youtube_video_id, tiktok_video_id FROM clips WHERE status = 'published' ORDER BY rowid DESC")
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
    let config_path = base_dir.join("config").join("config.yaml");
    let avatar_cache_path = base_dir.join("data").join("streamer_avatars.json");
    let avatar_cache: std::collections::HashMap<String, serde_json::Value> = if avatar_cache_path.exists() {
        fs::read_to_string(&avatar_cache_path)
            .ok()
            .and_then(|c| serde_json::from_str(&c).ok())
            .unwrap_or_default()
    } else {
        std::collections::HashMap::new()
    };

    let mut streamers = Vec::new();
    if config_path.exists() {
        if let Ok(content) = fs::read_to_string(&config_path) {
            if let Ok(val) = serde_yaml::from_str::<Value>(&content) {
                if let Some(list) = val.get("streamers").and_then(|s| s.as_array()) {
                    for item in list {
                        let name = item.get("name").and_then(|v| v.as_str()).unwrap_or_default().to_string();
                        let platform = item.get("platform").and_then(|v| v.as_str()).unwrap_or("twitch").to_string();
                        let enabled = item.get("enabled").and_then(|v| v.as_bool()).unwrap_or(true);
                        let min_clip_views = item.get("min_clip_views").and_then(|v| v.as_i64()).unwrap_or(30);
                        let max_clips_per_run = item.get("max_clips_per_run").and_then(|v| v.as_i64()).unwrap_or(2);
                        let layout = item.get("layout").and_then(|v| v.as_str()).unwrap_or("auto").to_string();

                        let clean_login = name.to_lowercase();
                        let av_entry = avatar_cache.get(&clean_login);
                        let avatar_url = av_entry
                            .and_then(|v| v.get("avatar_url"))
                            .and_then(|v| v.as_str())
                            .map(|s| s.to_string());
                        let display_name = av_entry
                            .and_then(|v| v.get("display_name"))
                            .and_then(|v| v.as_str())
                            .map(|s| s.to_string());
                        let has_custom_crops = Some(item.get("custom_crops").is_some());

                        streamers.push(StreamerConfig {
                            name,
                            platform,
                            enabled,
                            min_clip_views,
                            max_clips_per_run,
                            layout,
                            avatar_url,
                            display_name,
                            has_custom_crops,
                        });
                    }
                }
            }
        }
    }

    // 7. Account Status
    let yt_token_file = base_dir.join("config").join("oauth_token.json");
    let yt_secrets_file = base_dir.join("config").join("youtube_secrets.json");
    let youtube_connected = yt_token_file.exists() || yt_secrets_file.exists();

    let account_status = AccountStatus {
        youtube_connected,
        youtube_channel: if youtube_connected { "YouTube Kanal verbunden".to_string() } else { "Nicht verknüpft".to_string() },
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_fetch_dashboard() {
        let res = fetch_dashboard_data();
        assert!(res.is_ok(), "fetch_dashboard_data failed: {:?}", res.err());
        let data = res.unwrap();
        println!("Fetched counts: {:?}", data.counts);
        println!("Queue clips count: {}", data.queue_clips.len());
        println!("Ready clips count: {}", data.ready_clips.len());
        println!("Streamers count: {}", data.streamers.len());
        assert!(!data.streamers.is_empty(), "Should load streamers from config.yaml");
    }
}
