use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use serde_json::Value;

use crate::models::DashboardData;

fn get_base_dir() -> PathBuf {
    if Path::new("data").exists() {
        PathBuf::from(".")
    } else if Path::new("../data").exists() {
        PathBuf::from("..")
    } else {
        PathBuf::from(".")
    }
}

#[tauri::command]
pub fn get_dashboard_data() -> Result<DashboardData, String> {
    crate::db::fetch_dashboard_data()
}

#[tauri::command]
pub fn get_app_version() -> String {
    env!("CARGO_PKG_VERSION").to_string()
}

#[tauri::command]
pub fn open_folder(subfolder: String) -> Result<(), String> {
    let base = get_base_dir();
    let target = if subfolder.is_empty() {
        base
    } else {
        base.join(subfolder)
    };

    let target_str = target.canonicalize().unwrap_or(target);
    Command::new("explorer")
        .arg(target_str)
        .spawn()
        .map_err(|e| format!("Fehler beim Öffnen des Ordners: {}", e))?;

    Ok(())
}

#[tauri::command]
pub fn delete_queue_clip(clip_id: String) -> Result<bool, String> {
    let base = get_base_dir();
    let db_path = base.join("data").join("pipeline.db");
    let conn = rusqlite::Connection::open(&db_path).map_err(|e| e.to_string())?;

    conn.execute("DELETE FROM clips WHERE clip_id = ?", [&clip_id])
        .map_err(|e| e.to_string())?;

    // Clean up raw mp4 file if exists
    let raw_file = base.join("downloads").join("raw").join(format!("{}.mp4", clip_id));
    if raw_file.exists() {
        let _ = fs::remove_file(raw_file);
    }
    let txt_file = base.join("downloads").join("raw").join(format!("{}_transcript.txt", clip_id));
    if txt_file.exists() {
        let _ = fs::remove_file(txt_file);
    }

    Ok(true)
}

#[tauri::command]
pub fn save_clip_crop(
    clip_id: String,
    crop_data: Value,
    cam_filter: Option<String>,
    sub_position: Option<String>,
    sticker_text: Option<String>,
) -> Result<bool, String> {
    let base = get_base_dir();
    let meta_dir = base.join("output").join("metadata");
    fs::create_dir_all(&meta_dir).map_err(|e| e.to_string())?;

    let meta_file = meta_dir.join(format!("{}.json", clip_id));
    let mut meta_val = if meta_file.exists() {
        fs::read_to_string(&meta_file)
            .ok()
            .and_then(|s| serde_json::from_str::<Value>(&s).ok())
            .unwrap_or_else(|| serde_json::json!({}))
    } else {
        serde_json::json!({})
    };

    if let Some(obj) = meta_val.as_object_mut() {
        obj.insert("custom_crop".to_string(), crop_data);
        obj.insert("layout_mode".to_string(), serde_json::json!("custom"));
        if let Some(cf) = cam_filter {
            obj.insert("cam_filter".to_string(), serde_json::json!(cf));
        }
        if let Some(sp) = sub_position {
            obj.insert("sub_position".to_string(), serde_json::json!(sp));
        }
        if let Some(st) = sticker_text {
            obj.insert("sticker_text".to_string(), serde_json::json!(st));
        }
    }

    let serialized = serde_json::to_string_pretty(&meta_val).map_err(|e| e.to_string())?;
    fs::write(meta_file, serialized).map_err(|e| e.to_string())?;

    Ok(true)
}
