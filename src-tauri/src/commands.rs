use serde_json::{json, Value};
use std::path::PathBuf;
use tauri::AppHandle;

use crate::config::{
    add_streamer, get_data_root, get_metadata_dir, get_raw_clips_dir, get_shorts_dir,
    load_config, remove_streamer, save_config, update_all_streamers_min_views, update_streamer,
    StreamerEntry,
};
use crate::db::{
    fetch_dashboard_data, get_clip_by_id, open_connection, toggle_manually_published,
    update_clip_status,
};
use crate::gpu::{detect_gpus, get_encoder_catalog, select_best_encoder, EncoderProfile, GpuInfo};
use crate::layout::generate_thumbnail;
use crate::models::DashboardData;
use crate::pipeline::{process_all_pending, process_single_clip, run_twitch_harvest};
use crate::state::{cancel_active_render, status_manager};
use crate::twitch::{
    download_clip_file, harvest_channel, normalize_gql_time_filter, query_twitch_clips,
    refresh_streamer_avatars, save_harvested_clip, DiscoveredClip,
};
use crate::updater::{check_for_update, download_and_launch_update};

#[tauri::command]
pub fn get_dashboard_data() -> Result<DashboardData, String> {
    fetch_dashboard_data()
}

#[tauri::command]
pub fn get_app_version() -> String {
    env!("CARGO_PKG_VERSION").to_string()
}

#[tauri::command]
pub fn get_data_root_path() -> String {
    get_data_root().to_string_lossy().to_string()
}

#[tauri::command]
pub fn open_folder(folder_type: String) -> Result<(), String> {
    let target = match folder_type.as_str() {
        "shorts" => get_shorts_dir(),
        "raw" => get_raw_clips_dir(),
        "metadata" => get_metadata_dir(),
        _ => get_data_root(),
    };
    std::fs::create_dir_all(&target).map_err(|e| e.to_string())?;
    #[cfg(windows)]
    {
        std::process::Command::new("explorer")
            .arg(&target)
            .spawn()
            .map_err(|e| format!("Explorer-Startfehler: {e}"))?;
    }
    Ok(())
}

#[tauri::command]
pub fn delete_queue_clip(clip_id: String) -> Result<bool, String> {
    let conn = open_connection()?;
    conn.execute("DELETE FROM clips WHERE clip_id = ?1", [&clip_id])
        .map_err(|e| e.to_string())?;

    let raw_p = get_raw_clips_dir().join(format!("{clip_id}.mp4"));
    let short_p = get_shorts_dir().join(format!("short_{clip_id}.mp4"));
    let meta_p = get_metadata_dir().join(format!("{clip_id}.json"));
    let ass_p = get_metadata_dir().join(format!("{clip_id}.ass"));
    let thumb_p = get_data_root().join("thumbnails").join(format!("{clip_id}.jpg"));
    for p in [raw_p, short_p, meta_p, ass_p, thumb_p] {
        if p.exists() {
            let _ = std::fs::remove_file(p);
        }
    }
    Ok(true)
}

#[tauri::command]
pub fn save_clip_crop(clip_id: String, payload: Value) -> Result<bool, String> {
    let meta_dir = get_metadata_dir();
    std::fs::create_dir_all(&meta_dir).map_err(|e| e.to_string())?;
    let meta_path = meta_dir.join(format!("{clip_id}.json"));

    let mut meta: Value = if meta_path.exists() {
        std::fs::read_to_string(&meta_path)
            .ok()
            .and_then(|s| serde_json::from_str(&s).ok())
            .unwrap_or_else(|| json!({}))
    } else {
        json!({})
    };

    if let Some(obj) = meta.as_object_mut() {
        let crops = if payload.get("custom_crops").is_some() {
            payload.get("custom_crops").cloned().unwrap_or(payload.clone())
        } else {
            payload.clone()
        };

        obj.insert("custom_crops".to_string(), crops.clone());

        let mode = payload
            .get("layout_mode")
            .and_then(|m| m.as_str())
            .or_else(|| crops.get("mode").and_then(|m| m.as_str()))
            .unwrap_or("custom")
            .to_string();
        obj.insert("layout_mode".to_string(), Value::String(mode));

        if let Some(st) = payload.get("sticker_text").and_then(|s| s.as_str()) {
            obj.insert("sticker_text".to_string(), Value::String(st.to_string()));
            obj.insert("hook_text".to_string(), Value::String(st.to_string()));
        }
        if let Some(sp) = payload.get("sub_position").and_then(|s| s.as_str()) {
            obj.insert("sub_position".to_string(), Value::String(sp.to_string()));
        }
        if let Some(cf) = payload.get("cam_filter").and_then(|s| s.as_str()) {
            obj.insert("cam_filter".to_string(), Value::String(cf.to_string()));
        }
        if let Some(t) = payload.get("title").and_then(|s| s.as_str()) {
            obj.insert("title".to_string(), Value::String(t.to_string()));
            if let Ok(conn) = open_connection() {
                let _ = conn.execute(
                    "UPDATE clips SET ai_title = ?1 WHERE clip_id = ?2",
                    rusqlite::params![t, &clip_id],
                );
            }
        }
        if let Some(tr) = payload.get("transcript").and_then(|s| s.as_str()) {
            obj.insert("edited_transcript".to_string(), Value::String(tr.to_string()));
        }
    }

    let pretty = serde_json::to_string_pretty(&meta).map_err(|e| e.to_string())?;
    std::fs::write(&meta_path, pretty).map_err(|e| e.to_string())?;
    Ok(true)
}

#[tauri::command]
pub async fn trigger_twitch_run(app: AppHandle) -> Result<usize, String> {
    run_twitch_harvest(Some(app)).await
}

#[tauri::command]
pub fn detect_hardware_gpus() -> Vec<GpuInfo> {
    detect_gpus()
}

#[tauri::command]
pub fn get_available_encoders() -> Vec<EncoderProfile> {
    get_encoder_catalog()
}

#[tauri::command]
pub fn select_hardware_encoder(preferred: String) -> EncoderProfile {
    select_best_encoder(&preferred)
}

fn url_decode_simple(s: &str) -> String {
    let mut bytes = Vec::with_capacity(s.len());
    let raw = s.as_bytes();
    let mut i = 0;
    while i < raw.len() {
        if raw[i] == b'%' && i + 2 < raw.len() {
            if let Ok(hex) = std::str::from_utf8(&raw[i + 1..i + 3]) {
                if let Ok(b) = u8::from_str_radix(hex, 16) {
                    bytes.push(b);
                    i += 3;
                    continue;
                }
            }
        }
        if raw[i] == b'+' {
            bytes.push(b' ');
        } else {
            bytes.push(raw[i]);
        }
        i += 1;
    }
    String::from_utf8_lossy(&bytes).to_string()
}

/// 100% Rust In-Process API-Dispatcher für alle Studio-UI Endpunkte (kein Flask/Port 5000).
#[tauri::command]
pub async fn api_proxy(
    app: AppHandle,
    endpoint: String,
    method: Option<String>,
    body: Option<String>,
) -> Result<String, String> {
    let clean_path = endpoint
        .split('?')
        .next()
        .unwrap_or(&endpoint)
        .trim_end_matches('/');
    let req_method = method.unwrap_or_else(|| "GET".to_string()).to_uppercase();
    let payload: Value = body
        .as_deref()
        .and_then(|s| serde_json::from_str(s).ok())
        .unwrap_or(Value::Null);

    // 1. Dashboard & Status & Version
    if clean_path == "/api/dashboard" {
        let dash = fetch_dashboard_data()?;
        return serde_json::to_string(&dash).map_err(|e| e.to_string());
    }
    if clean_path == "/api/status" {
        let st = status_manager().get_state();
        return serde_json::to_string(&st).map_err(|e| e.to_string());
    }
    if clean_path == "/api/version" {
        return Ok(json!({ "version": env!("CARGO_PKG_VERSION") }).to_string());
    }

    // 2. Harvest & Processing
    if clean_path == "/api/run" && req_method == "POST" {
        let app_clone = app.clone();
        tokio::spawn(async move {
            let _ = run_twitch_harvest(Some(app_clone)).await;
        });
        return Ok(json!({ "success": true, "ok": true, "started": true }).to_string());
    }
    if clean_path == "/api/process-all" && req_method == "POST" {
        let app_clone = app.clone();
        tokio::spawn(async move {
            let _ = process_all_pending(Some(app_clone)).await;
        });
        return Ok(json!({ "success": true, "ok": true, "started": true }).to_string());
    }
    if let Some(clip_id) = clean_path.strip_prefix("/process-one/") {
        let cid = url_decode_simple(clip_id);
        let app_clone = app.clone();
        tokio::spawn(async move {
            let _ = process_single_clip(&cid, Some(app_clone)).await;
        });
        return Ok(json!({ "success": true, "ok": true, "started": true }).to_string());
    }
    if let Some(rest) = clean_path.strip_prefix("/api/clip/") {
        if let Some(cid) = rest.strip_suffix("/cancel") {
            let ok = cancel_active_render(&url_decode_simple(cid));
            return Ok(json!({ "success": ok, "ok": ok }).to_string());
        }
        if let Some(cid) = rest.strip_suffix("/toggle-published") {
            let published = toggle_manually_published(&url_decode_simple(cid))?;
            return Ok(json!({ "success": true, "ok": true, "is_manually_published": published }).to_string());
        }
        if let Some(cid) = rest.strip_suffix("/detect-cam") {
            let _ = cid;
            return Ok(json!({ "detected": false, "box": null }).to_string());
        }
        if let Some(cid) = rest.strip_suffix("/save-crop") {
            let cid = url_decode_simple(cid);
            let render_now = payload
                .get("render_now")
                .and_then(|v| v.as_bool())
                .unwrap_or(false);

            save_clip_crop(cid.clone(), payload)?;

            if render_now {
                let app_clone = app.clone();
                let cid_clone = cid.clone();
                tokio::spawn(async move {
                    let _ = process_single_clip(&cid_clone, Some(app_clone)).await;
                });
            }
            return Ok(json!({ "success": true, "ok": true, "rendering": render_now }).to_string());
        }
        if let Some(cid) = rest.strip_suffix("/meta") {
            let cid = url_decode_simple(cid);
            let meta_path = get_metadata_dir().join(format!("{cid}.json"));
            let mut meta: Value = if meta_path.exists() {
                std::fs::read_to_string(&meta_path)
                    .ok()
                    .and_then(|s| serde_json::from_str(&s).ok())
                    .unwrap_or_else(|| json!({}))
            } else {
                json!({})
            };

            if req_method == "GET" {
                return Ok(meta.to_string());
            }
            if let (Some(dst), Some(src)) = (meta.as_object_mut(), payload.as_object()) {
                for (k, v) in src {
                    dst.insert(k.clone(), v.clone());
                }
            }
            std::fs::create_dir_all(get_metadata_dir()).map_err(|e| e.to_string())?;
            let pretty = serde_json::to_string_pretty(&meta).map_err(|e| e.to_string())?;
            std::fs::write(&meta_path, pretty).map_err(|e| e.to_string())?;
            return Ok(json!({ "success": true, "ok": true, "meta": meta }).to_string());
        }
    }

    // 2b. Studio Save / Rerender / Schedule / Publish / Delete
    if let Some(cid) = clean_path.strip_prefix("/save/") {
        if req_method == "POST" {
            let cid = url_decode_simple(cid);
            let action = payload
                .get("action")
                .and_then(|v| v.as_str())
                .unwrap_or("save");

            if action == "delete" {
                delete_queue_clip(cid)?;
                return Ok(json!({ "success": true, "ok": true }).to_string());
            }

            if let Some(title_val) = payload.get("title").and_then(|v| v.as_str()) {
                let conn = open_connection()?;
                conn.execute(
                    "UPDATE clips SET ai_title = ?1 WHERE clip_id = ?2",
                    rusqlite::params![title_val, &cid],
                )
                .map_err(|e| e.to_string())?;

                let meta_dir = get_metadata_dir();
                std::fs::create_dir_all(&meta_dir).map_err(|e| e.to_string())?;
                let meta_path = meta_dir.join(format!("{cid}.json"));
                let mut meta: Value = if meta_path.exists() {
                    std::fs::read_to_string(&meta_path)
                        .ok()
                        .and_then(|s| serde_json::from_str(&s).ok())
                        .unwrap_or_else(|| json!({}))
                } else {
                    json!({})
                };
                if let Some(obj) = meta.as_object_mut() {
                    obj.insert("title".to_string(), Value::String(title_val.to_string()));
                }
                if let Ok(pretty) = serde_json::to_string_pretty(&meta) {
                    let _ = std::fs::write(&meta_path, pretty);
                }
            }

            if let Some(crops_val) = payload.get("custom_crops") {
                save_clip_crop(cid.clone(), crops_val.clone())?;
            }

            match action {
                "rerender" => {
                    let cid_clone = cid.clone();
                    let app_clone = app.clone();
                    tokio::spawn(async move {
                        let _ = process_single_clip(&cid_clone, Some(app_clone)).await;
                    });
                }
                "schedule" => {
                    update_clip_status(&cid, "scheduled")?;
                }
                "publish_now" => {
                    update_clip_status(&cid, "published")?;
                }
                _ => {}
            }
            return Ok(json!({ "success": true, "ok": true }).to_string());
        }
    }

    // 3. Queue Delete / Cleanup
    if let Some(cid) = clean_path.strip_prefix("/queue/delete/") {
        delete_queue_clip(url_decode_simple(cid))?;
        return Ok(json!({ "success": true, "ok": true }).to_string());
    }
    if clean_path == "/queue/delete-older" && req_method == "POST" {
        let days = payload.get("days").and_then(|v| v.as_i64());
        let conn = open_connection()?;
        let ids: Vec<String> = if let Some(d) = days {
            let mut stmt = conn
                .prepare(
                    "SELECT clip_id FROM clips WHERE status = 'harvested' AND date(COALESCE(clip_created_at, harvested_at), 'localtime') < date('now', 'localtime', ?1)",
                )
                .map_err(|e| e.to_string())?;
            let rows = stmt
                .query_map([format!("-{d} days")], |row| row.get(0))
                .map_err(|e| e.to_string())?;
            rows.filter_map(Result::ok).collect()
        } else {
            let mut stmt = conn
                .prepare(
                    "SELECT clip_id FROM clips WHERE status = 'harvested' AND date(COALESCE(clip_created_at, harvested_at), 'localtime') < date('now', 'localtime')",
                )
                .map_err(|e| e.to_string())?;
            let rows = stmt
                .query_map([], |row| row.get(0))
                .map_err(|e| e.to_string())?;
            rows.filter_map(Result::ok).collect()
        };

        let mut deleted = 0;
        for cid in ids {
            if delete_queue_clip(cid).is_ok() {
                deleted += 1;
            }
        }
        return Ok(json!({ "success": true, "ok": true, "deleted": deleted }).to_string());
    }

    // 4. Scheduling
    if let Some(cid) = clean_path.strip_prefix("/schedule-one/") {
        update_clip_status(&url_decode_simple(cid), "scheduled")?;
        return Ok(json!({ "success": true, "ok": true }).to_string());
    }
    if let Some(cid) = clean_path.strip_prefix("/schedule/publish-now/") {
        update_clip_status(&url_decode_simple(cid), "published")?;
        return Ok(json!({ "success": true, "ok": true }).to_string());
    }
    if let Some(cid) = clean_path.strip_prefix("/schedule/cancel/") {
        update_clip_status(&url_decode_simple(cid), "ready")?;
        return Ok(json!({ "success": true, "ok": true }).to_string());
    }

    // 5. Streamers CRUD & Layout
    if clean_path == "/api/streamers/add" && req_method == "POST" {
        let name = payload
            .get("name")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim()
            .to_string();
        let min_views = payload
            .get("min_clip_views")
            .and_then(|v| v.as_i64())
            .unwrap_or(100);
        let max_clips = payload
            .get("max_clips")
            .and_then(|v| v.as_i64())
            .unwrap_or(3);
        let layout = payload
            .get("layout")
            .and_then(|v| v.as_str())
            .unwrap_or("auto");
        let added = add_streamer(&name, min_views, max_clips, layout)?;
        let _ = refresh_streamer_avatars(&[name]).await;
        return Ok(json!({ "success": added, "ok": added, "added": added }).to_string());
    }
    if let Some(name) = clean_path.strip_prefix("/api/streamers/remove/") {
        let removed = remove_streamer(&url_decode_simple(name))?;
        return Ok(json!({ "success": removed, "ok": removed }).to_string());
    }
    if clean_path == "/api/streamers/update" && req_method == "POST" {
        let name = payload
            .get("name")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let min_views = payload.get("min_clip_views").and_then(|v| v.as_i64());
        let max_clips = payload.get("max_clips").and_then(|v| v.as_i64());
        let layout = payload.get("layout").and_then(|v| v.as_str());
        let enabled = payload.get("enabled").and_then(|v| v.as_bool());
        let custom_crops = payload.get("custom_crops").cloned();
        let ok = update_streamer(name, min_views, max_clips, layout, enabled, custom_crops)?;
        return Ok(json!({ "success": ok, "ok": ok }).to_string());
    }
    if clean_path == "/api/streamers/update-all-views" && req_method == "POST" {
        let min_views = payload
            .get("min_clip_views")
            .and_then(|v| v.as_i64())
            .unwrap_or(100);
        let count = update_all_streamers_min_views(min_views)?;
        return Ok(json!({ "success": true, "ok": true, "updated": count }).to_string());
    }
    if let Some(rest) = clean_path.strip_prefix("/api/streamers/") {
        if let Some(name) = rest.strip_suffix("/layout") {
            let sname = url_decode_simple(name);
            let layout = payload.get("layout").and_then(|v| v.as_str());
            let custom_crops = payload.get("custom_crops").cloned();
            let ok = update_streamer(&sname, None, None, layout, None, custom_crops)?;
            return Ok(json!({ "success": ok, "ok": ok }).to_string());
        }
        if let Some(name) = rest.strip_suffix("/config") {
            let sname = url_decode_simple(name);
            if req_method == "GET" {
                let cfg = load_config();
                let found = cfg
                    .streamers
                    .into_iter()
                    .find(|s| s.name.eq_ignore_ascii_case(&sname));
                return Ok(serde_json::to_string(&found).unwrap_or_else(|_| "null".to_string()));
            } else {
                let min_views = payload.get("min_clip_views").and_then(|v| v.as_i64());
                let max_clips = payload.get("max_clips").and_then(|v| v.as_i64());
                let layout = payload.get("layout").and_then(|v| v.as_str());
                let enabled = payload.get("enabled").and_then(|v| v.as_bool());
                let custom_crops = payload.get("custom_crops").cloned();
                let ok =
                    update_streamer(&sname, min_views, max_clips, layout, enabled, custom_crops)?;
                return Ok(json!({ "success": ok, "ok": ok }).to_string());
            }
        }
        if let Some(name) = rest.strip_suffix("/sample-clip") {
            let sname = url_decode_simple(name);
            let conn = open_connection()?;
            let existing_id: Option<String> = conn
                .query_row(
                    "SELECT clip_id FROM clips WHERE LOWER(streamer) = LOWER(?1) ORDER BY COALESCE(clip_created_at, harvested_at) DESC, rowid DESC LIMIT 1",
                    [&sname],
                    |row| row.get(0),
                )
                .ok();
            if let Some(cid) = existing_id {
                return Ok(json!({ "success": true, "ok": true, "clip_id": cid }).to_string());
            }
            let temp_entry = StreamerEntry {
                name: sname.clone(),
                platform: "twitch".to_string(),
                enabled: true,
                min_clip_views: 0,
                max_clips_per_run: 1,
                layout: "auto".to_string(),
                custom_crops: None,
                extra: Default::default(),
            };
            let _ = harvest_channel(&temp_entry, "last_week", true).await?;
            let new_id: Option<String> = conn
                .query_row(
                    "SELECT clip_id FROM clips WHERE LOWER(streamer) = LOWER(?1) ORDER BY COALESCE(clip_created_at, harvested_at) DESC, rowid DESC LIMIT 1",
                    [&sname],
                    |row| row.get(0),
                )
                .ok();
            if let Some(cid) = new_id {
                let _ = generate_thumbnail(&cid, false);
                return Ok(json!({ "success": true, "ok": true, "clip_id": cid }).to_string());
            }
            return Err(format!("Kein Beispiel-Clip für {sname} gefunden."));
        }
    }

    // 6. Settings
    if clean_path == "/api/settings" {
        if req_method == "GET" {
            let cfg = load_config();
            return Ok(json!({
                "success": true,
                "enabled": cfg.autopilot.enabled,
                "interval_minutes": cfg.autopilot.interval_minutes,
                "time_filter": cfg.autopilot.time_filter,
                "fallback_to_week": cfg.autopilot.fallback_to_week,
                "auto_render": cfg.autopilot.auto_render,
                "hardware_encoder": cfg.video.hardware_encoder,
                "whisper_model": cfg.video.whisper_model,
            })
            .to_string());
        } else {
            let mut cfg = load_config();
            // Flaches UI-Format aus #settings-form
            if let Some(en) = payload.get("enabled").and_then(|v| v.as_bool()) {
                cfg.autopilot.enabled = en;
            }
            if let Some(iv) = payload.get("interval_minutes").and_then(|v| v.as_i64()) {
                cfg.autopilot.interval_minutes = iv;
            }
            if let Some(tf) = payload.get("time_filter").and_then(|v| v.as_str()) {
                cfg.autopilot.time_filter = tf.to_string();
                cfg.twitch.time_filter = tf.to_string();
            }
            if let Some(fb) = payload.get("fallback_to_week").and_then(|v| v.as_bool()) {
                cfg.autopilot.fallback_to_week = fb;
            }
            if let Some(ar) = payload.get("auto_render").and_then(|v| v.as_bool()) {
                cfg.autopilot.auto_render = ar;
            }
            if let Some(hw) = payload.get("hardware_encoder").and_then(|v| v.as_str()) {
                cfg.video.hardware_encoder = hw.to_string();
            }
            if let Some(wm) = payload.get("whisper_model").and_then(|v| v.as_str()) {
                cfg.video.whisper_model = wm.to_string();
            }
            // Optionales verschachteltes Format
            if let Some(tw) = payload.get("twitch") {
                if let Some(cid) = tw.get("client_id").and_then(|v| v.as_str()) {
                    cfg.twitch.client_id = cid.to_string();
                }
                if let Some(sec) = tw.get("client_secret").and_then(|v| v.as_str()) {
                    cfg.twitch.client_secret = sec.to_string();
                }
            }
            if let Some(vid) = payload.get("video") {
                if let Some(wm) = vid.get("whisper_model").and_then(|v| v.as_str()) {
                    cfg.video.whisper_model = wm.to_string();
                }
                if let Some(hw) = vid.get("hardware_encoder").and_then(|v| v.as_str()) {
                    cfg.video.hardware_encoder = hw.to_string();
                }
                if let Some(an) = vid.get("audio_normalize").and_then(|v| v.as_bool()) {
                    cfg.video.audio_normalize = an;
                }
                if let Some(nv) = vid.get("use_nvenc").and_then(|v| v.as_bool()) {
                    cfg.video.use_nvenc = nv;
                }
                if let Some(wl) = vid.get("whisper_language").and_then(|v| v.as_str()) {
                    cfg.video.extra.insert(
                        "whisper_language".to_string(),
                        serde_yaml::Value::String(wl.to_string()),
                    );
                }
            }
            if let Some(ap) = payload.get("autopilot") {
                if let Some(en) = ap.get("enabled").and_then(|v| v.as_bool()) {
                    cfg.autopilot.enabled = en;
                }
                if let Some(iv) = ap.get("interval_minutes").and_then(|v| v.as_i64()) {
                    cfg.autopilot.interval_minutes = iv;
                }
            }
            save_config(&cfg)?;
            return Ok(json!({ "success": true, "ok": true }).to_string());
        }
    }

    // 7. Hardware & Export
    if clean_path == "/api/hardware/gpus" {
        return serde_json::to_string(&detect_gpus()).map_err(|e| e.to_string());
    }
    if clean_path == "/api/hardware/encoders" {
        return serde_json::to_string(&get_encoder_catalog()).map_err(|e| e.to_string());
    }
    if clean_path == "/api/hardware/select" && req_method == "POST" {
        let pref = payload
            .get("encoder")
            .and_then(|v| v.as_str())
            .unwrap_or("auto");
        let mut cfg = load_config();
        cfg.video.hardware_encoder = pref.to_string();
        save_config(&cfg)?;
        let prof = select_best_encoder(pref);
        return serde_json::to_string(&prof).map_err(|e| e.to_string());
    }

    if clean_path == "/api/export-all-ready" && req_method == "POST" {
        let dest_dir = tokio::task::spawn_blocking(|| {
            rfd::FileDialog::new()
                .set_title("Zielordner für alle fertigen Shorts wählen")
                .pick_folder()
        })
        .await
        .map_err(|e| e.to_string())?;

        let Some(folder) = dest_dir else {
            return Ok(json!({ "ok": false, "cancelled": true }).to_string());
        };

        let dash = fetch_dashboard_data()?;
        let mut exported = 0usize;
        for clip in dash.ready_clips {
            let src = get_shorts_dir().join(format!("short_{}.mp4", clip.clip_id));
            if src.exists() {
                let dst = folder.join(format!("short_{}.mp4", clip.clip_id));
                if std::fs::copy(&src, &dst).is_ok() {
                    exported += 1;
                }
            }
        }
        return Ok(json!({ "success": true, "ok": true,
            "exported": exported,
            "folder": folder.to_string_lossy()
        })
        .to_string());
    }

    if let Some(cid) = clean_path.strip_prefix("/api/export/") {
        let cid = url_decode_simple(cid);
        let clip = get_clip_by_id(&cid)?
            .ok_or_else(|| format!("Clip nicht gefunden: {cid}"))?;
        let src = if let Some(ref sp) = clip.short_path {
            if !sp.is_empty() {
                PathBuf::from(sp)
            } else {
                get_shorts_dir().join(format!("short_{cid}.mp4"))
            }
        } else {
            get_shorts_dir().join(format!("short_{cid}.mp4"))
        };
        if !src.exists() {
            return Err("Short-Datei wurde noch nicht gerendert.".to_string());
        }

        let default_name = format!("short_{cid}.mp4");
        let save_path = tokio::task::spawn_blocking(move || {
            rfd::FileDialog::new()
                .set_file_name(&default_name)
                .add_filter("MP4 Video", &["mp4"])
                .save_file()
        })
        .await
        .map_err(|e| e.to_string())?;

        let Some(dst) = save_path else {
            return Ok(json!({ "ok": false, "cancelled": true }).to_string());
        };
        std::fs::copy(&src, &dst).map_err(|e| format!("Export-Fehler: {e}"))?;
        return Ok(json!({ "success": true, "ok": true, "path": dst.to_string_lossy() }).to_string());
    }

    // 8. Twitch Clip-Explorer (Manuelle Suche & Direkt-Import)
    if clean_path == "/api/twitch/search-clips" {
        let query_str = endpoint.split('?').nth(1).unwrap_or("");
        let mut streamer = String::new();
        let mut timeframe = "LAST_DAY".to_string();
        let mut limit = 24usize;
        for pair in query_str.split('&') {
            if let Some((k, v)) = pair.split_once('=') {
                let decoded = url_decode_simple(v);
                match k {
                    "streamer" => streamer = decoded.trim().to_string(),
                    "timeframe" => timeframe = decoded,
                    "limit" => limit = decoded.parse::<usize>().unwrap_or(24).clamp(1, 50),
                    _ => {}
                }
            }
        }
        if streamer.is_empty() {
            return Ok(json!({ "success": false, "error": "Kein Streamer-Name angegeben." }).to_string());
        }
        let tf = normalize_gql_time_filter(&timeframe);
        let clips = query_twitch_clips(&streamer, limit, tf).await?;
        let conn = open_connection()?;
        let enriched: Vec<Value> = clips
            .into_iter()
            .map(|c| {
                let db_status: Option<String> = conn
                    .query_row(
                        "SELECT status FROM clips WHERE clip_id = ?1",
                        [&c.clip_id],
                        |row| row.get(0),
                    )
                    .ok();
                json!({
                    "clip_id": c.clip_id,
                    "streamer": c.streamer,
                    "title": c.title,
                    "url": c.url,
                    "view_count": c.view_count,
                    "duration": c.duration,
                    "created_at": c.created_at,
                    "thumbnail_url": c.thumbnail_url,
                    "db_status": db_status,
                })
            })
            .collect();

        return Ok(json!({
            "success": true,
            "time_filter": tf,
            "streamer": {
                "login": streamer.to_lowercase(),
                "display_name": streamer,
            },
            "clips": enriched
        })
        .to_string());
    }

    if clean_path == "/api/twitch/import-clip" && req_method == "POST" {
        let clip_id = payload
            .get("clip_id")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim()
            .to_string();
        if clip_id.is_empty() {
            return Ok(json!({ "success": false, "error": "clip_id fehlt." }).to_string());
        }
        let streamer = payload
            .get("streamer")
            .and_then(|v| v.as_str())
            .unwrap_or("twitch")
            .to_string();
        let title = payload
            .get("title")
            .and_then(|v| v.as_str())
            .unwrap_or("Clip")
            .to_string();
        let url = payload
            .get("url")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        let view_count = payload.get("view_count").and_then(|v| v.as_i64()).unwrap_or(0);
        let duration = payload.get("duration").and_then(|v| v.as_f64()).unwrap_or(30.0);
        let created_at = payload
            .get("created_at")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        let mode = payload
            .get("mode")
            .and_then(|v| v.as_str())
            .unwrap_or("studio");

        let raw_path = download_clip_file(&url, &clip_id).await?;
        let discovered = DiscoveredClip {
            clip_id: clip_id.clone(),
            streamer,
            title,
            url,
            view_count,
            duration,
            created_at,
            thumbnail_url: String::new(),
        };
        save_harvested_clip(&discovered, &raw_path)?;
        let _ = generate_thumbnail(&clip_id, false);

        if mode != "queue" {
            update_clip_status(&clip_id, "ready")?;
        }
        return Ok(json!({ "success": true, "ok": true, "clip_id": clip_id }).to_string());
    }

    // 9. Updater
    if clean_path == "/api/system/check-update" {
        let res = check_for_update().await?;
        return Ok(res.to_string());
    }
    if clean_path == "/api/system/perform-update" && req_method == "POST" {
        let url = payload
            .get("download_url")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let res = download_and_launch_update(url).await?;
        return Ok(res.to_string());
    }

    Err(format!("Unbekannter API-Endpunkt: {req_method} {clean_path}"))
}

