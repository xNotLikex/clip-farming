from pathlib import Path
import os
import sys
import yaml
from typing import Dict, Any, List

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

# Initialize directories on import
ensure_directories()
