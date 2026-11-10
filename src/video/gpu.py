import subprocess
import shutil
import platform
import json
from typing import Dict, List, Any, Optional

def get_installed_gpus() -> List[Dict[str, Any]]:
    """Liest alle installierten Grafikkarten unter Windows aus."""
    gpus = []
    if platform.system() == "Windows":
        try:
            cmd = ["powershell", "-NoProfile", "-Command", 
                   "Get-CimInstance Win32_VideoController | Select-Object Name, AdapterRAM | ConvertTo-Json -Compress"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if res.returncode == 0 and res.stdout.strip():
                data = json.loads(res.stdout)
                if isinstance(data, dict):
                    data = [data]
                for item in data:
                    name = item.get("Name", "Unbekannte GPU")
                    ram_bytes = item.get("AdapterRAM") or 0
                    ram_mb = int(ram_bytes / (1024 * 1024)) if ram_bytes else 0
                    
                    is_nvidia = "nvidia" in name.lower() or "geforce" in name.lower() or "rtx" in name.lower() or "gtx" in name.lower()
                    is_amd = "amd" in name.lower() or "radeon" in name.lower()
                    is_intel = "intel" in name.lower() or "arc" in name.lower() or "iris" in name.lower() or "uhd" in name.lower()
                    is_onboard = ("graphics" in name.lower() and not "rx" in name.lower()) or ram_mb < 1500

                    vendor = "nvidia" if is_nvidia else ("amd" if is_amd else ("intel" if is_intel else "other"))
                    gpus.append({
                        "name": name,
                        "ram_mb": ram_mb,
                        "vendor": vendor,
                        "is_onboard": is_onboard
                    })
        except Exception as e:
            print(f"[!] Fehler bei GPU-Erkennung: {e}")
    return gpus

def test_ffmpeg_encoder(encoder_name: str) -> bool:
    """Prüft mit einem 1-Frame Testvideo, ob ein FFmpeg-Encoder auf der Hardware funktioniert."""
    ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
    cmd = [
        ffmpeg_bin, "-y",
        "-f", "lavfi", "-i", "testsrc=duration=0.1:size=320x240:rate=10",
        "-c:v", encoder_name,
        "-f", "null", "-"
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, timeout=5)
        return res.returncode == 0
    except Exception:
        return False

def get_best_video_encoder(preferred: str = "auto") -> Dict[str, Any]:
    """
    Ermittelt den besten funktionierenden Hardware-Encoder.
    Optionen für preferred: 'auto', 'nvenc', 'amf', 'qsv', 'mf', 'cpu'
    """
    # 1. Definierte Profile für alle Hersteller & Onboard-GPUs
    ENCODER_PROFILES = {
        "nvenc": {
            "name": "NVIDIA NVENC",
            "codec": "h264_nvenc",
            "args": ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "23"],
            "desc": "NVIDIA GeForce / RTX Hardware-Beschleunigung"
        },
        "amf": {
            "name": "AMD AMF",
            "codec": "h264_amf",
            "args": ["-c:v", "h264_amf", "-quality", "speed", "-b:v", "6M"],
            "desc": "AMD Radeon dedizierte GPU & Onboard APU Beschleunigung"
        },
        "qsv": {
            "name": "Intel QuickSync",
            "codec": "h264_qsv",
            "args": ["-c:v", "h264_qsv", "-preset", "medium", "-global_quality", "23"],
            "desc": "Intel Arc & Core iGPU QuickSync"
        },
        "mf": {
            "name": "Windows Media Foundation",
            "codec": "h264_mf",
            "args": ["-c:v", "h264_mf", "-b:v", "6M"],
            "desc": "Universeller Windows Hardware-Encoder (AMD Onboard, Intel & NVIDIA)"
        },
        "cpu": {
            "name": "CPU (Software x264)",
            "codec": "libx264",
            "args": ["-c:v", "libx264", "-preset", "fast", "-crf", "22", "-threads", "0"],
            "desc": "Universeller CPU-Fallback für alle Systeme"
        }
    }

    # Wenn der Nutzer explizit gewählt hat
    if preferred != "auto" and preferred in ENCODER_PROFILES:
        prof = ENCODER_PROFILES[preferred]
        if preferred == "cpu" or test_ffmpeg_encoder(prof["codec"]):
            return prof

    # Automatische Erkennung nach Priorität
    gpus = get_installed_gpus()
    has_nvidia = any(g["vendor"] == "nvidia" for g in gpus)
    has_amd = any(g["vendor"] == "amd" for g in gpus)
    has_intel = any(g["vendor"] == "intel" for g in gpus)

    # 1. NVIDIA NVENC
    if has_nvidia and test_ffmpeg_encoder("h264_nvenc"):
        return ENCODER_PROFILES["nvenc"]

    # 2. AMD AMF
    if has_amd and test_ffmpeg_encoder("h264_amf"):
        return ENCODER_PROFILES["amf"]

    # 3. Intel QuickSync
    if has_intel and test_ffmpeg_encoder("h264_qsv"):
        return ENCODER_PROFILES["qsv"]

    # 4. Windows Media Foundation (perfekt für Onboard AMD & Intel APUs)
    if test_ffmpeg_encoder("h264_mf"):
        return ENCODER_PROFILES["mf"]

    # 5. Fallback auf Multi-Core CPU
    return ENCODER_PROFILES["cpu"]

if __name__ == "__main__":
    print("=== ERKANNTEL GRAFIKKARTEN ===")
    for g in get_installed_gpus():
        typ = "Onboard / APU" if g["is_onboard"] else "Dediziert"
        print(f" - {g['name']} ({g['ram_mb']} MB VRAM, {g['vendor'].upper()}, {typ})")
    
    print("\n=== OPTIMALER ENCODER ===")
    best = get_best_video_encoder("auto")
    print(f"Gewählt: {best['name']} ({best['codec']})")
    print(f"Parameter: {' '.join(best['args'])}")
    print(f"Beschreibung: {best['desc']}")
