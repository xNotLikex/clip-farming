use serde::{Deserialize, Serialize};
use serde_yaml::Value as YamlValue;
use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::{Mutex, OnceLock};

static CONFIG_LOCK: OnceLock<Mutex<()>> = OnceLock::new();

fn config_lock() -> &'static Mutex<()> {
    CONFIG_LOCK.get_or_init(|| Mutex::new(()))
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CropRect {
    pub x: f64,
    pub y: f64,
    pub w: f64,
    pub h: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CustomCrops {
    pub cam: Option<CropRect>,
    pub game: Option<CropRect>,
}

pub fn preset_corner_crops(layout: &str) -> Option<CustomCrops> {
    let rect = match layout {
        "top_left" => CropRect { x: 0.0, y: 0.0, w: 0.30, h: 0.30 },
        "top_right" => CropRect { x: 0.70, y: 0.0, w: 0.30, h: 0.30 },
        "bottom_left" => CropRect { x: 0.0, y: 0.70, w: 0.30, h: 0.30 },
        "bottom_right" => CropRect { x: 0.70, y: 0.70, w: 0.30, h: 0.30 },
        _ => return None,
    };
    Some(CustomCrops {
        cam: Some(rect),
        game: Some(CropRect { x: 0.0, y: 0.0, w: 1.0, h: 1.0 }),
    })
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StreamerEntry {
    pub name: String,
    #[serde(default = "default_platform")]
    pub platform: String,
    #[serde(default = "default_true")]
    pub enabled: bool,
    #[serde(default = "default_min_views")]
    pub min_clip_views: i64,
    #[serde(default = "default_max_clips")]
    pub max_clips_per_run: i64,
    #[serde(default = "default_layout")]
    pub layout: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub custom_crops: Option<serde_json::Value>,
    #[serde(flatten)]
    pub extra: HashMap<String, YamlValue>,
}

fn default_platform() -> String { "twitch".to_string() }
fn default_true() -> bool { true }
fn default_min_views() -> i64 { 30 }
fn default_max_clips() -> i64 { 2 }
fn default_layout() -> String { "auto".to_string() }

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct TwitchConfig {
    #[serde(default)]
    pub client_id: String,
    #[serde(default)]
    pub client_secret: String,
    #[serde(default = "default_time_filter")]
    pub time_filter: String,
    #[serde(flatten)]
    pub extra: HashMap<String, YamlValue>,
}

fn default_time_filter() -> String { "LAST_DAY".to_string() }

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VideoConfig {
    #[serde(default = "default_true")]
    pub use_nvenc: bool,
    #[serde(default = "default_auto")]
    pub hardware_encoder: String,
    #[serde(default = "default_small")]
    pub whisper_model: String,
    #[serde(default = "default_true")]
    pub audio_normalize: bool,
    #[serde(flatten)]
    pub extra: HashMap<String, YamlValue>,
}

impl Default for VideoConfig {
    fn default() -> Self {
        Self {
            use_nvenc: true,
            hardware_encoder: "auto".to_string(),
            whisper_model: "small".to_string(),
            audio_normalize: true,
            extra: HashMap::new(),
        }
    }
}

fn default_auto() -> String { "auto".to_string() }
fn default_small() -> String { "small".to_string() }

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AutopilotConfig {
    #[serde(default = "default_true")]
    pub enabled: bool,
    #[serde(default = "default_interval")]
    pub interval_minutes: i64,
    #[serde(default = "default_time_filter")]
    pub time_filter: String,
    #[serde(default = "default_true")]
    pub fallback_to_week: bool,
    #[serde(default)]
    pub auto_render: bool,
    #[serde(flatten)]
    pub extra: HashMap<String, YamlValue>,
}

impl Default for AutopilotConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            interval_minutes: 30,
            time_filter: "LAST_DAY".to_string(),
            fallback_to_week: true,
            auto_render: false,
            extra: HashMap::new(),
        }
    }
}

fn default_interval() -> i64 { 30 }

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct AppConfig {
    #[serde(default)]
    pub twitch: TwitchConfig,
    #[serde(default)]
    pub video: VideoConfig,
    #[serde(default)]
    pub autopilot: AutopilotConfig,
    #[serde(default)]
    pub streamers: Vec<StreamerEntry>,
    #[serde(flatten)]
    pub extra: HashMap<String, YamlValue>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AutopilotSettings {
    pub enabled: bool,
    pub interval_minutes: i64,
    pub time_filter: String,
    pub fallback_to_week: bool,
    pub auto_render: bool,
    pub hardware_encoder: String,
    pub whisper_model: String,
}

fn is_dir_writable(dir: &Path) -> bool {
    if fs::create_dir_all(dir).is_err() {
        return false;
    }
    let probe = dir.join(".write_probe");
    if fs::write(&probe, b"ok").is_ok() {
        let _ = fs::remove_file(&probe);
        true
    } else {
        false
    }
}

/// Liefert das schreibbare Daten-Wurzelverzeichnis (100% portabel neben der .exe):
/// 1. Wenn `CLIP_FARMING_DATA_DIR` gesetzt ist -> dieses nutzen (ideal für Tests).
/// 2. Dev-Modus (`target/debug` oder `target/release` im Repo): Repo-Root nutzen, wenn dort `data/`/`config/` liegt.
/// 3. Portable-Standard: Direkt im Ordner der `.exe` (`exe_dir`), sofern beschreibbar (keine Daten in AppData!).
/// 4. Nur falls `exe_dir` schreibgeschützt ist (z. B. `Program Files`): `%LOCALAPPDATA%\Clip-Farming`.
pub fn get_data_root() -> PathBuf {
    if let Some(override_dir) = std::env::var_os("CLIP_FARMING_DATA_DIR") {
        let p = PathBuf::from(override_dir);
        let _ = ensure_directories_in(&p);
        return p;
    }

    if let Ok(exe_path) = std::env::current_exe() {
        if let Some(exe_dir) = exe_path.parent() {
            // Dev-Modus unter src-tauri/target/{debug,release} -> Repo-Root prüfen
            let is_cargo_target = exe_dir
                .parent()
                .and_then(|p| p.file_name())
                .and_then(|n| n.to_str())
                == Some("target");
            if is_cargo_target {
                for candidate in [Path::new("."), Path::new("..")] {
                    if (candidate.join("data").exists() || candidate.join("config").exists())
                        && is_dir_writable(&candidate.join("data"))
                    {
                        let _ = ensure_directories_in(candidate);
                        return candidate.to_path_buf();
                    }
                }
            }

            // Portable-Standard: direkt neben clip-farming.exe speichern
            if is_dir_writable(exe_dir) {
                let _ = ensure_directories_in(exe_dir);
                return exe_dir.to_path_buf();
            }
        }
    }

    for candidate in [Path::new("."), Path::new("..")] {
        if (candidate.join("data").exists() || candidate.join("config").exists())
            && is_dir_writable(&candidate.join("data"))
        {
            let _ = ensure_directories_in(candidate);
            return candidate.to_path_buf();
        }
    }

    let app_data = std::env::var_os("LOCALAPPDATA")
        .or_else(|| std::env::var_os("HOME"))
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."));
    let root = app_data.join("Clip-Farming");
    let _ = ensure_directories_in(&root);
    root
}

pub fn ensure_directories_in(root: &Path) -> std::io::Result<()> {
    for sub in [
        "data",
        "config",
        "downloads/raw",
        "output/shorts",
        "output/metadata",
        "models",
        "logs",
    ] {
        fs::create_dir_all(root.join(sub))?;
    }
    Ok(())
}

pub fn get_config_path() -> PathBuf {
    get_data_root().join("config").join("config.yaml")
}

pub fn get_db_path() -> PathBuf {
    get_data_root().join("data").join("pipeline.db")
}

pub fn get_raw_clips_dir() -> PathBuf {
    get_data_root().join("downloads").join("raw")
}

pub fn get_shorts_dir() -> PathBuf {
    get_data_root().join("output").join("shorts")
}

pub fn get_metadata_dir() -> PathBuf {
    get_data_root().join("output").join("metadata")
}

pub fn get_models_dir() -> PathBuf {
    get_data_root().join("models")
}

/// Findet gebündelte Sidecar-Binaries (z.B. `ffmpeg.exe`, `ffprobe.exe`, `whisper-cli.exe`).
pub fn resolve_binary(name: &str) -> PathBuf {
    let exe_name = if cfg!(windows) && !name.to_lowercase().ends_with(".exe") {
        format!("{}.exe", name)
    } else {
        name.to_string()
    };
    let stem = name.trim_end_matches(".exe");
    let target_triple_name = if cfg!(windows) {
        format!("{}-x86_64-pc-windows-msvc.exe", stem)
    } else {
        stem.to_string()
    };

    if let Ok(exe_path) = std::env::current_exe() {
        if let Some(exe_dir) = exe_path.parent() {
            for rel in [
                exe_dir.join(&exe_name),
                exe_dir.join("bin").join(&exe_name),
                exe_dir.join("binaries").join(&target_triple_name),
                exe_dir.join("binaries").join(&exe_name),
            ] {
                if rel.exists() {
                    return rel;
                }
            }
        }
    }

    let data_bin = get_data_root().join("bin").join(&exe_name);
    if data_bin.exists() {
        return data_bin;
    }

    PathBuf::from(exe_name)
}

pub fn load_config() -> AppConfig {
    let _guard = config_lock().lock().unwrap();
    let cfg_path = get_config_path();
    let mut cfg = if cfg_path.exists() {
        match fs::read_to_string(&cfg_path) {
            Ok(content) => serde_yaml::from_str::<AppConfig>(&content).unwrap_or_default(),
            Err(_) => AppConfig::default(),
        }
    } else {
        AppConfig::default()
    };

    if let Ok(cid) = std::env::var("TWITCH_CLIENT_ID") {
        if !cid.trim().is_empty() {
            cfg.twitch.client_id = cid.trim().to_string();
        }
    }
    if let Ok(csec) = std::env::var("TWITCH_CLIENT_SECRET") {
        if !csec.trim().is_empty() {
            cfg.twitch.client_secret = csec.trim().to_string();
        }
    }

    cfg
}

pub fn save_config(cfg: &AppConfig) -> Result<(), String> {
    let _guard = config_lock().lock().unwrap();
    let cfg_path = get_config_path();
    if let Some(parent) = cfg_path.parent() {
        fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    let yaml_str = serde_yaml::to_string(cfg).map_err(|e| e.to_string())?;
    let tmp_path = cfg_path.with_extension("yaml.tmp");
    fs::write(&tmp_path, yaml_str).map_err(|e| e.to_string())?;
    fs::rename(&tmp_path, &cfg_path).map_err(|e| e.to_string())?;
    Ok(())
}

pub fn add_streamer(name: &str, min_views: i64, max_clips: i64, layout: &str) -> Result<bool, String> {
    let clean = name.trim().to_lowercase();
    if clean.is_empty() {
        return Ok(false);
    }
    let mut cfg = load_config();
    if let Some(existing) = cfg.streamers.iter_mut().find(|s| s.name.eq_ignore_ascii_case(&clean)) {
        existing.min_clip_views = min_views.max(1);
        existing.max_clips_per_run = max_clips.max(1);
        existing.layout = layout.to_string();
        existing.enabled = true;
    } else {
        cfg.streamers.push(StreamerEntry {
            name: clean,
            platform: "twitch".to_string(),
            enabled: true,
            min_clip_views: min_views.max(1),
            max_clips_per_run: max_clips.max(1),
            layout: layout.to_string(),
            custom_crops: None,
            extra: HashMap::new(),
        });
    }
    save_config(&cfg)?;
    Ok(true)
}

pub fn remove_streamer(name: &str) -> Result<bool, String> {
    let clean = name.trim().to_lowercase();
    let mut cfg = load_config();
    let before = cfg.streamers.len();
    cfg.streamers.retain(|s| !s.name.eq_ignore_ascii_case(&clean));
    if cfg.streamers.len() < before {
        save_config(&cfg)?;
        return Ok(true);
    }
    Ok(false)
}

pub fn update_streamer(
    name: &str,
    min_views: Option<i64>,
    max_clips: Option<i64>,
    layout: Option<&str>,
    enabled: Option<bool>,
    custom_crops: Option<serde_json::Value>,
) -> Result<bool, String> {
    let clean = name.trim().to_lowercase();
    let mut cfg = load_config();
    let mut found = false;
    for s in &mut cfg.streamers {
        if s.name.eq_ignore_ascii_case(&clean) {
            if let Some(mv) = min_views {
                s.min_clip_views = mv.max(1);
            }
            if let Some(mc) = max_clips {
                s.max_clips_per_run = mc.max(1);
            }
            if let Some(l) = layout {
                s.layout = l.to_string();
                if custom_crops.is_none() {
                    if let Some(preset) = preset_corner_crops(l) {
                        s.custom_crops = serde_json::to_value(preset).ok();
                    }
                }
            }
            if let Some(en) = enabled {
                s.enabled = en;
            }
            if let Some(cc) = custom_crops {
                if cc.as_str() == Some("reset") || cc == serde_json::json!({}) || cc == serde_json::json!(false) {
                    s.custom_crops = None;
                } else {
                    s.custom_crops = Some(cc);
                }
            }
            found = true;
            break;
        }
    }
    if found {
        save_config(&cfg)?;
    }
    Ok(found)
}

pub fn update_all_streamers_min_views(min_views: i64) -> Result<usize, String> {
    let val = min_views.max(1);
    let mut cfg = load_config();
    for s in &mut cfg.streamers {
        s.min_clip_views = val;
    }
    let count = cfg.streamers.len();
    save_config(&cfg)?;
    Ok(count)
}

pub fn get_autopilot_settings() -> AutopilotSettings {
    let cfg = load_config();
    let tf = if cfg.autopilot.time_filter.is_empty() {
        if cfg.twitch.time_filter.is_empty() {
            "LAST_DAY".to_string()
        } else {
            cfg.twitch.time_filter.clone()
        }
    } else {
        cfg.autopilot.time_filter.clone()
    };
    AutopilotSettings {
        enabled: cfg.autopilot.enabled,
        interval_minutes: cfg.autopilot.interval_minutes.max(1),
        time_filter: tf,
        fallback_to_week: cfg.autopilot.fallback_to_week,
        auto_render: cfg.autopilot.auto_render,
        hardware_encoder: cfg.video.hardware_encoder,
        whisper_model: cfg.video.whisper_model,
    }
}

pub fn save_autopilot_settings(
    enabled: Option<bool>,
    interval_minutes: Option<i64>,
    time_filter: Option<&str>,
    fallback_to_week: Option<bool>,
    auto_render: Option<bool>,
    hardware_encoder: Option<&str>,
    whisper_model: Option<&str>,
) -> Result<(), String> {
    let mut cfg = load_config();
    if let Some(v) = enabled {
        cfg.autopilot.enabled = v;
    }
    if let Some(v) = interval_minutes {
        cfg.autopilot.interval_minutes = v.max(1);
    }
    if let Some(v) = time_filter {
        let tf = v.trim().to_uppercase();
        if matches!(tf.as_str(), "LAST_DAY" | "LAST_WEEK" | "LAST_MONTH" | "ALL_TIME") {
            cfg.autopilot.time_filter = tf.clone();
            cfg.twitch.time_filter = tf;
        }
    }
    if let Some(v) = fallback_to_week {
        cfg.autopilot.fallback_to_week = v;
    }
    if let Some(v) = auto_render {
        cfg.autopilot.auto_render = v;
    }
    if let Some(v) = hardware_encoder {
        let hw = v.trim().to_lowercase();
        if !hw.is_empty() {
            cfg.video.hardware_encoder = hw;
        }
    }
    if let Some(v) = whisper_model {
        let wm = v.trim().to_lowercase();
        if !wm.is_empty() {
            cfg.video.whisper_model = wm;
        }
    }
    save_config(&cfg)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_config_roundtrip_and_streamer_crud() {
        let tmp = std::env::temp_dir().join(format!("cf_cfg_test_{}", std::process::id()));
        let _ = fs::remove_dir_all(&tmp);
        fs::create_dir_all(&tmp).unwrap();
        unsafe {
            std::env::set_var("CLIP_FARMING_DATA_DIR", &tmp);
        }

        assert!(add_streamer("Trymacs", 100, 3, "auto").unwrap());
        assert!(update_streamer("trymacs", Some(250), None, Some("top_right"), None, None).unwrap());

        let cfg = load_config();
        assert_eq!(cfg.streamers.len(), 1);
        assert_eq!(cfg.streamers[0].min_clip_views, 250);
        assert_eq!(cfg.streamers[0].layout, "top_right");
        assert!(cfg.streamers[0].custom_crops.is_some());

        assert_eq!(update_all_streamers_min_views(500).unwrap(), 1);
        assert_eq!(load_config().streamers[0].min_clip_views, 500);

        assert!(remove_streamer("trymacs").unwrap());
        assert!(load_config().streamers.is_empty());

        unsafe {
            std::env::remove_var("CLIP_FARMING_DATA_DIR");
        }
        let _ = fs::remove_dir_all(&tmp);
    }
}
