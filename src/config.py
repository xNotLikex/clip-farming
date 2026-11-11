from pathlib import Path
import os
import sys
import yaml
from typing import Dict, Any, List, Optional

# Absolute Project Root (Portable - relative to this file)
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Portable CUDA & Local Bin Loader for Windows
if sys.platform == "win32":
    try:
        # Reconfigure console encoding
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    # Add local bin folder (for portable ffmpeg, ffprobe) to PATH
    bin_folder = PROJECT_ROOT / "bin"
    if bin_folder.exists():
        os.environ["PATH"] = str(bin_folder) + os.pathsep + os.environ.get("PATH", "")
        try:
            os.add_dll_directory(str(bin_folder))
        except Exception:
            pass

    # Add portable nvidia CUDA libraries (cublas, cudnn) to PATH and DLL search directory
    nvidia_dir = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
    if nvidia_dir.exists():
        for package_dir in nvidia_dir.iterdir():
            bin_dir = package_dir / "bin"
            if bin_dir.exists():
                os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
                try:
                    os.add_dll_directory(str(bin_dir))
                except Exception:
                    pass

# Default directories
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
DOWNLOADS_DIR = PROJECT_ROOT / "downloads"
RAW_CLIPS_DIR = DOWNLOADS_DIR / "raw"
CHAT_DIR = DOWNLOADS_DIR / "chat"
OUTPUT_DIR = PROJECT_ROOT / "output"
SHORTS_OUTPUT_DIR = OUTPUT_DIR / "shorts"
METADATA_OUTPUT_DIR = OUTPUT_DIR / "metadata"
FONTS_DIR = PROJECT_ROOT / "fonts"

def ensure_directories():
    """Ensure all required portable directories exist."""
    for folder in [CONFIG_DIR, DATA_DIR, DOWNLOADS_DIR, RAW_CLIPS_DIR, 
                   CHAT_DIR, OUTPUT_DIR, SHORTS_OUTPUT_DIR, METADATA_OUTPUT_DIR, FONTS_DIR]:
        folder.mkdir(parents=True, exist_ok=True)

def load_config() -> Dict[str, Any]:
    """Load configuration from config/config.yaml."""
    ensure_directories()
    config_file = CONFIG_DIR / "config.yaml"
    if not config_file.exists():
        raise FileNotFoundError(f"Konfigurationsdatei nicht gefunden: {config_file}")
    
    with open(config_file, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def save_config(cfg: Dict[str, Any]):
    """Save configuration back to config/config.yaml."""
    config_file = CONFIG_DIR / "config.yaml"
    with open(config_file, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, allow_unicode=True, sort_keys=False)

def get_streamers() -> List[Dict[str, Any]]:
    """Gibt die Liste aller konfigurierten Streamer zurück."""
    cfg = load_config()
    return cfg.get("streamers", [])

def add_streamer(name: str, min_views: int = 30, max_clips: int = 2, layout: str = "auto") -> bool:
    """Fügt einen neuen Streamer zur Liste in config.yaml hinzu."""
    clean_name = name.strip().lower()
    if not clean_name:
        return False
    cfg = load_config()
    streamers = cfg.get("streamers", [])
    for s in streamers:
        if s.get("name", "").lower() == clean_name:
            s["enabled"] = True
            s["min_clip_views"] = int(min_views)
            s["max_clips_per_run"] = int(max_clips)
            save_config(cfg)
            return True
    
    streamers.append({
        "name": clean_name,
        "platform": "twitch",
        "enabled": True,
        "min_clip_views": int(min_views),
        "max_clips_per_run": int(max_clips),
        "layout": layout
    })
    cfg["streamers"] = streamers
    save_config(cfg)
    return True

def remove_streamer(name: str) -> bool:
    """Entfernt einen Streamer aus der Liste in config.yaml."""
    clean_name = name.strip().lower()
    cfg = load_config()
    streamers = cfg.get("streamers", [])
    new_list = [s for s in streamers if s.get("name", "").lower() != clean_name]
    if len(new_list) != len(streamers):
        cfg["streamers"] = new_list
        save_config(cfg)
        return True
    return False

PRESET_CORNER_CROPS = {
    "top_left": {
        "mode": "split",
        "enabled": True,
        "cam": {"x_pct": 0.02, "y_pct": 0.03, "w_pct": 0.28, "h_pct": 0.30, "enabled": True},
        "game": {"x_pct": 0.247, "y_pct": 0.0, "w_pct": 0.506, "h_pct": 1.0, "enabled": True}
    },
    "top_right": {
        "mode": "split",
        "enabled": True,
        "cam": {"x_pct": 0.70, "y_pct": 0.03, "w_pct": 0.28, "h_pct": 0.30, "enabled": True},
        "game": {"x_pct": 0.247, "y_pct": 0.0, "w_pct": 0.506, "h_pct": 1.0, "enabled": True}
    },
    "bottom_left": {
        "mode": "split",
        "enabled": True,
        "cam": {"x_pct": 0.02, "y_pct": 0.67, "w_pct": 0.28, "h_pct": 0.30, "enabled": True},
        "game": {"x_pct": 0.247, "y_pct": 0.0, "w_pct": 0.506, "h_pct": 1.0, "enabled": True}
    },
    "bottom_right": {
        "mode": "split",
        "enabled": True,
        "cam": {"x_pct": 0.70, "y_pct": 0.67, "w_pct": 0.28, "h_pct": 0.30, "enabled": True},
        "game": {"x_pct": 0.247, "y_pct": 0.0, "w_pct": 0.506, "h_pct": 1.0, "enabled": True}
    }
}

def update_streamer(
    name: str, 
    min_views: Optional[int] = None, 
    max_clips: Optional[int] = None, 
    layout: Optional[str] = None, 
    enabled: Optional[bool] = None,
    custom_crops: Optional[Any] = None
) -> bool:
    """Aktualisiert die Einstellungen eines Streamers in config.yaml."""
    clean_name = name.strip().lower()
    cfg = load_config()
    streamers = cfg.get("streamers", [])
    found = False
    for s in streamers:
        if s.get("name", "").lower() == clean_name:
            if min_views is not None:
                s["min_clip_views"] = int(min_views)
            if max_clips is not None:
                s["max_clips_per_run"] = int(max_clips)
            if layout is not None:
                s["layout"] = str(layout)
                if str(layout) in PRESET_CORNER_CROPS and custom_crops is None:
                    s["custom_crops"] = PRESET_CORNER_CROPS[str(layout)]
            if enabled is not None:
                s["enabled"] = bool(enabled)
            if custom_crops is not None:
                if custom_crops == "reset" or custom_crops == {} or custom_crops is False:
                    s.pop("custom_crops", None)
                else:
                    s["custom_crops"] = custom_crops
            found = True
            break
    if found:
        save_config(cfg)
        return True
    return False

def update_all_streamers_min_views(min_views: int) -> int:
    """Setzt die Mindest-Views für alle Streamer in config.yaml auf denselben Wert."""
    val = max(1, int(min_views))
    cfg = load_config()
    streamers = cfg.get("streamers", [])
    count = 0
    for s in streamers:
        s["min_clip_views"] = val
        count += 1
    save_config(cfg)
    return count

def get_autopilot_settings() -> Dict[str, Any]:
    """Gibt die aktuellen Autopilot- und Prüfintervall-Einstellungen zurück."""
    cfg = load_config()
    autopilot = cfg.get("autopilot", {})
    return {
        "enabled": autopilot.get("enabled", True),
        "interval_minutes": int(autopilot.get("interval_minutes", 30)),
        "time_filter": autopilot.get("time_filter", cfg.get("twitch", {}).get("time_filter", "LAST_DAY")),
        "fallback_to_week": autopilot.get("fallback_to_week", True),
        "auto_render": autopilot.get("auto_render", False),
        "hardware_encoder": cfg.get("video", {}).get("hardware_encoder", "auto"),
        "whisper_model": cfg.get("video", {}).get("whisper_model", "small"),
    }

def save_autopilot_settings(settings: Dict[str, Any]) -> bool:
    """Speichert Autopilot- und Prüfintervall-Einstellungen in config.yaml."""
    cfg = load_config()
    if "autopilot" not in cfg:
        cfg["autopilot"] = {}
    
    if "enabled" in settings:
        cfg["autopilot"]["enabled"] = bool(settings["enabled"])
    if "interval_minutes" in settings:
        cfg["autopilot"]["interval_minutes"] = max(1, int(settings["interval_minutes"]))
    if "time_filter" in settings:
        tf = str(settings["time_filter"]).strip().upper()
        if tf in ["LAST_DAY", "LAST_WEEK", "LAST_MONTH"]:
            cfg["autopilot"]["time_filter"] = tf
            if "twitch" in cfg:
                cfg["twitch"]["time_filter"] = tf
    if "fallback_to_week" in settings:
        cfg["autopilot"]["fallback_to_week"] = bool(settings["fallback_to_week"])
    if "auto_render" in settings:
        cfg["autopilot"]["auto_render"] = bool(settings["auto_render"])
    if "hardware_encoder" in settings:
        if "video" not in cfg:
            cfg["video"] = {}
        cfg["video"]["hardware_encoder"] = str(settings["hardware_encoder"]).strip().lower()
    if "whisper_model" in settings:
        if "video" not in cfg:
            cfg["video"] = {}
        cfg["video"]["whisper_model"] = str(settings["whisper_model"]).strip().lower()

    save_config(cfg)
    return True

# Initialize directories on import
ensure_directories()
