use serde_json::Value;
use std::path::PathBuf;
use tauri::AppHandle;

use crate::config::{get_metadata_dir, get_raw_clips_dir, load_config};
use crate::db::{
    get_clip_by_id, get_pending_clips, update_clip_error, update_clip_rendered, update_clip_status,
};
use crate::layout::{generate_thumbnail, probe_video, render_short, RenderOptions};
use crate::state::{status_manager, worker_lock};
use crate::subtitles::{align_words_with_edited_text, generate_ass, TranscriptSegment};
use crate::twitch::{harvest_channel, refresh_streamer_avatars};
use crate::whisper::transcribe_video;

/// Startet den Twitch-Harvester für alle aktiven Streamer.
pub async fn run_twitch_harvest(app: Option<AppHandle>) -> Result<usize, String> {
    let _guard = worker_lock()
        .try_lock()
        .map_err(|_| "Es läuft bereits ein Hintergrund-Task.".to_string())?;

    let mgr = status_manager();
    if let Some(a) = app {
        mgr.set_app_handle(a);
    }
    mgr.set_task("harvesting", "Suche neue Twitch Clips...", "", "");

    let cfg = load_config();
    let active_streamers: Vec<_> = cfg
        .streamers
        .into_iter()
        .filter(|s| s.enabled)
        .collect();

    if active_streamers.is_empty() {
        mgr.set_task("idle", "Keine aktiven Streamer konfiguriert.", "", "");
        return Ok(0);
    }

    let mut total_harvested = 0usize;
    let total_streamers = active_streamers.len().max(1);

    for (idx, st) in active_streamers.iter().enumerate() {
        let pct = (((idx as f64) / (total_streamers as f64)) * 90.0) as i32;
        mgr.set_progress(
            pct,
            0,
            &format!("{}/{}", idx + 1, total_streamers),
            Some(&format!("Durchsuche {}...", st.name)),
            None,
        );

        match harvest_channel(st, "last_day", true).await {
            Ok(count) => {
                total_harvested += count;
            }
            Err(e) => {
                mgr.log(&format!("[!] Harvest-Fehler für {}: {e}", st.name));
            }
        }
    }

    let _ = generate_thumbnail_for_pending();

    let logins: Vec<String> = active_streamers.iter().map(|s| s.name.clone()).collect();
    let _ = refresh_streamer_avatars(&logins).await;
    mgr.set_task("idle", &format!("{total_harvested} neue Clips geladen."), "", "");
    Ok(total_harvested)
}

fn generate_thumbnail_for_pending() {
    if let Ok(pending) = get_pending_clips() {
        for c in pending {
            let _ = generate_thumbnail(&c.clip_id, false);
        }
    }
}

/// Verarbeitet einen einzelnen Clip (Whisper-Transkription + ASS + 9:16 FFmpeg-Render).
pub async fn process_single_clip_inner(
    clip_id: &str,
    app: Option<AppHandle>,
) -> Result<PathBuf, String> {
    let mgr = status_manager();
    if let Some(a) = app {
        mgr.set_app_handle(a);
    }

    let clip = get_clip_by_id(clip_id)
        .map_err(|e| e.to_string())?
        .ok_or_else(|| format!("Clip nicht in Datenbank gefunden: {clip_id}"))?;

    let raw_path = if let Some(ref rp) = clip.raw_path {
        if !rp.is_empty() && PathBuf::from(rp).exists() {
            PathBuf::from(rp)
        } else {
            get_raw_clips_dir().join(format!("{clip_id}.mp4"))
        }
    } else {
        get_raw_clips_dir().join(format!("{clip_id}.mp4"))
    };

    if !raw_path.exists() {
        let err = format!("Rohvideo nicht gefunden: {}", raw_path.display());
        let _ = update_clip_error(clip_id, &err);
        return Err(err);
    }

    let _ = update_clip_status(clip_id, "processing");
    mgr.set_task(
        "processing",
        "Erstelle Untertitel & AI-Transkript...",
        &clip.original_title,
        &clip.streamer,
    );
    mgr.set_progress(10, 15, "Whisper", None, Some(clip_id));

    let meta_path = get_metadata_dir().join(format!("{clip_id}.json"));
    let mut meta_val: Value = if meta_path.exists() {
        std::fs::read_to_string(&meta_path)
            .ok()
            .and_then(|s| serde_json::from_str(&s).ok())
            .unwrap_or_else(|| serde_json::json!({}))
    } else {
        serde_json::json!({})
    };

    let sub_position = meta_val
        .get("sub_position")
        .and_then(|v| v.as_str())
        .unwrap_or("bottom")
        .to_string();
    let sub_style = meta_val
        .get("sub_style")
        .and_then(|v| v.as_str())
        .unwrap_or("yellow")
        .to_string();
    let sub_enabled = meta_val
        .get("subtitles_enabled")
        .and_then(|v| v.as_bool())
        .unwrap_or(true);
    let hook_text = meta_val
        .get("hook_text")
        .or_else(|| meta_val.get("sticker_text"))
        .and_then(|v| v.as_str())
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_string)
        .or_else(|| {
            clip.ai_title
                .as_deref()
                .map(str::trim)
                .filter(|s| !s.is_empty())
                .map(str::to_string)
                .or_else(|| {
                    if !clip.original_title.trim().is_empty() {
                        Some(clip.original_title.clone())
                    } else {
                        None
                    }
                })
        });

    let layout_mode = meta_val
        .get("layout_mode")
        .and_then(|v| v.as_str())
        .unwrap_or("auto")
        .to_string();
    let custom_crops = meta_val.get("custom_crops").filter(|v| !v.is_null()).cloned();

    let ass_path = if sub_enabled {
        let mut segments: Vec<TranscriptSegment> = meta_val
            .get("transcript_segments")
            .and_then(|v| serde_json::from_value(v.clone()).ok())
            .unwrap_or_default();

        if segments.is_empty() {
            match transcribe_video(&raw_path).await {
                Ok(segs) => {
                    segments = segs;
                    if let Some(obj) = meta_val.as_object_mut() {
                        obj.insert(
                            "transcript_segments".to_string(),
                            serde_json::to_value(&segments).unwrap_or(Value::Null),
                        );
                        let full_txt = segments
                            .iter()
                            .map(|s| s.text.trim())
                            .collect::<Vec<_>>()
                            .join(" ");
                        obj.insert("transcript".to_string(), Value::String(full_txt));
                    }
                    if let Ok(pretty) = serde_json::to_string_pretty(&meta_val) {
                        let _ = std::fs::create_dir_all(get_metadata_dir());
                        let _ = std::fs::write(&meta_path, pretty);
                    }
                }
                Err(e) => {
                    mgr.log(&format!("[!] Whisper Warnung für {clip_id}: {e}"));
                }
            }
        }

        if let Some(edited) = meta_val
            .get("edited_transcript")
            .and_then(|v| v.as_str())
            .map(str::trim)
            .filter(|s| !s.is_empty())
        {
            let dur = probe_video(&raw_path).duration;
            segments = align_words_with_edited_text(&segments, edited, dur);
        }

        if !segments.is_empty() {
            let p = get_metadata_dir().join(format!("{clip_id}.ass"));
            match generate_ass(&segments, &p, &sub_position, &sub_style) {
                Ok(ass) => Some(ass),
                Err(e) => {
                    mgr.log(&format!("[!] ASS-Fehler für {clip_id}: {e}"));
                    None
                }
            }
        } else {
            None
        }
    } else {
        None
    };

    mgr.set_task(
        "rendering",
        "Rendere 9:16 Short...",
        &clip.original_title,
        &clip.streamer,
    );

    let opts = RenderOptions {
        clip_id: clip_id.to_string(),
        raw_video_path: raw_path,
        ass_subtitle_path: ass_path,
        layout_mode,
        custom_crops,
        header_sticker_text: hook_text.clone(),
        streamer_name: Some(clip.streamer.clone()),
    };

    let clip_id_owned = clip_id.to_string();
    let render_res = tokio::task::spawn_blocking(move || {
        render_short(&opts, |pct, eta, speed| {
            status_manager().set_progress(
                pct as i32,
                eta as i64,
                speed,
                None,
                Some(&clip_id_owned),
            );
        })
    })
    .await
    .map_err(|e| format!("Render-Thread Fehler: {e}"))?;

    match render_res {
        Ok(out_path) => {
            let out_str = out_path.to_string_lossy().to_string();
            let _ = update_clip_rendered(clip_id, &out_str, hook_text.as_deref());
            mgr.set_task("idle", &format!("Short {clip_id} fertiggestellt."), "", "");
            Ok(out_path)
        }
        Err(e) => {
            let _ = update_clip_error(clip_id, &e);
            mgr.set_task("error", &format!("Fehler bei {clip_id}: {e}"), "", "");
            Err(e)
        }
    }
}

/// Verarbeitet einen Clip unter Worker-Lock.
pub async fn process_single_clip(clip_id: &str, app: Option<AppHandle>) -> Result<PathBuf, String> {
    let _guard = worker_lock()
        .try_lock()
        .map_err(|_| "Es läuft bereits ein Rendering-Task.".to_string())?;
    process_single_clip_inner(clip_id, app).await
}

/// Verarbeitet alle ausstehenden Clips in der Queue nacheinander.
pub async fn process_all_pending(app: Option<AppHandle>) -> Result<usize, String> {
    let _guard = worker_lock()
        .try_lock()
        .map_err(|_| "Es läuft bereits ein Hintergrund-Task.".to_string())?;

    let pending = get_pending_clips().map_err(|e| e.to_string())?;
    let mut done = 0usize;
    for clip in pending {
        if process_single_clip_inner(&clip.clip_id, app.clone())
            .await
            .is_ok()
        {
            done += 1;
        }
    }
    Ok(done)
}

/// Startet die optionale Autopilot-Endlosschleife im Hintergrund.
pub fn start_autopilot_loop(app: AppHandle) {
    tokio::spawn(async move {
        loop {
            let cfg = load_config();
            let interval_mins = cfg.autopilot.interval_minutes.max(5) as u64;
            tokio::time::sleep(std::time::Duration::from_secs(interval_mins * 60)).await;

            let cfg_now = load_config();
            if !cfg_now.autopilot.enabled {
                continue;
            }
            if worker_lock().try_lock().is_err() {
                continue;
            }
            drop(worker_lock().try_lock());

            let _ = run_twitch_harvest(Some(app.clone())).await;
            let _ = process_all_pending(Some(app.clone())).await;
        }
    });
}
