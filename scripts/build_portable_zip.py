"""
Erstellt ein sauberes, 100% portables Windows-ZIP-Paket von Clip Farming Studio.
Enthaelt:
  - clip-farming.exe (Desktop App)
  - runtime/ (Vollstaendiges, eigenstaendiges Python 3.12 inkl. PyTorch, Whisper, OpenCV)
  - bin/ (Portable ffmpeg.exe und ffprobe.exe)
  - src/ (Python Backend Source)
  - ui/ (Frontend Assets)
  - fonts/ (Untertitel-Schriftarten)
  - config/ (Bereinigte Konfiguration OHNE private Tokens / Secrets)
  - Leere data/, downloads/, output/ Ordner
"""

import os
import sys
import shutil
import zipfile
import yaml
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = PROJECT_ROOT / "dist"
STAGE_DIR = DIST_DIR / "Clip-Farming"
ZIP_PATH = PROJECT_ROOT / "Clip-Farming-Portable.zip"
PYTHON_BASE = Path(r"C:\Users\rausc\AppData\Local\Programs\Python\Python312")
FFMPEG_BIN = Path(r"C:\ffmpeg\bin")

def log(msg: str):
    print(f"[PORTABLE BUILDER] {msg}", flush=True)

def clean_staging():
    if STAGE_DIR.exists():
        log(f"Loesche altes Staging-Verzeichnis {STAGE_DIR}...")
        shutil.rmtree(STAGE_DIR, ignore_errors=True)
    STAGE_DIR.mkdir(parents=True, exist_ok=True)

def copy_executable():
    log("Kopiere clip-farming.exe...")
    exe_src = PROJECT_ROOT / "clip-farming.exe"
    if not exe_src.exists():
        exe_src = PROJECT_ROOT / "src-tauri" / "target" / "release" / "clip-farming.exe"
    shutil.copy2(exe_src, STAGE_DIR / "clip-farming.exe")

def copy_ffmpeg():
    log("Kopiere portable ffmpeg.exe und ffprobe.exe nach bin/...")
    bin_target = STAGE_DIR / "bin"
    bin_target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(FFMPEG_BIN / "ffmpeg.exe", bin_target / "ffmpeg.exe")
    shutil.copy2(FFMPEG_BIN / "ffprobe.exe", bin_target / "ffprobe.exe")

def copy_sources():
    log("Kopiere src/, ui/ und fonts/...")
    def ignore_patterns(folder, files):
        return [f for f in files if f in ("__pycache__", ".pytest_cache", ".git") or f.endswith(".pyc")]

    shutil.copytree(PROJECT_ROOT / "src", STAGE_DIR / "src", ignore=ignore_patterns)
    shutil.copytree(PROJECT_ROOT / "ui", STAGE_DIR / "ui", ignore=ignore_patterns)
    shutil.copytree(PROJECT_ROOT / "fonts", STAGE_DIR / "fonts", ignore=ignore_patterns)

def copy_sanitized_config():
    log("Erstelle bereinigte config/ (entferne private Tokens & Session-IDs)...")
    config_target = STAGE_DIR / "config"
    config_target.mkdir(parents=True, exist_ok=True)

    # config.yaml bereinigen
    config_src = PROJECT_ROOT / "config" / "config.yaml"
    with open(config_src, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    # Private Secrets loeschen
    if "publishing" in cfg:
        if "tiktok" in cfg["publishing"]:
            cfg["publishing"]["tiktok"]["session_id"] = ""
        if "youtube" in cfg["publishing"]:
            cfg["publishing"]["youtube"]["client_secrets_file"] = "config/youtube_secrets.json"

    if "ai_copywriter" in cfg:
        cfg["ai_copywriter"]["api_key"] = ""

    if "twitch" in cfg:
        cfg["twitch"]["client_id"] = ""
        cfg["twitch"]["client_secret"] = ""

    with open(config_target / "config.yaml", "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    # youtube_secrets.example.json Vorlage erstellen
    example_secrets = {
        "installed": {
            "client_id": "DEINE_GOOGLE_CLIENT_ID.apps.googleusercontent.com",
            "client_secret": "DEIN_GOOGLE_CLIENT_SECRET",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "redirect_uris": ["http://localhost"]
        }
    }
    import json
    with open(config_target / "youtube_secrets.example.json", "w", encoding="utf-8") as f:
        json.dump(example_secrets, f, indent=2)

def setup_empty_folders():
    log("Erstelle leere Verzeichnisse fuer data/, downloads/ und output/...")
    for sub in [
        STAGE_DIR / "data",
        STAGE_DIR / "downloads" / "raw",
        STAGE_DIR / "downloads" / "chat",
        STAGE_DIR / "output" / "shorts",
        STAGE_DIR / "output" / "metadata",
    ]:
        sub.mkdir(parents=True, exist_ok=True)
        (sub / ".gitkeep").touch()

def create_readme():
    log("Erstelle README.txt und STARTEN.bat...")
    readme_content = """============================================================
  CLIP FARMING STUDIO (Portable Windows Edition)
============================================================

SCHNELLSTART:
1. Den gesamten Ordner an einen beliebigen Ort entpacken.
2. Doppelklick auf 'clip-farming.exe' (oder 'STARTEN.bat').

HINWEISE:
- Python 3.12, FFmpeg sowie alle benoetigten KI-Modelle
  (Faster-Whisper, PyTorch, OpenCV, Flask) sind bereits
  vollstaendig und portabel in den Ordnern 'runtime/' und 'bin/'
  enthalten.
- Es ist KEINE separate Installation von Python oder FFmpeg
  auf deinem PC erforderlich!
- Alle Pfade, SQLite-Datenbanken und Ordner richten sich beim
  ersten Start automatisch frisch und isoliert ein.

Viel Erfolg beim Clip-Farming!
============================================================
"""
    with open(STAGE_DIR / "README.txt", "w", encoding="utf-8") as f:
        f.write(readme_content)

    bat_content = "@echo off\r\nstart \"\" \"%~dp0clip-farming.exe\"\r\n"
    with open(STAGE_DIR / "STARTEN.bat", "w", encoding="utf-8") as f:
        f.write(bat_content)

def build_portable_runtime():
    log("Baue portables Python-Runtime-Verzeichnis...")
    runtime_dir = STAGE_DIR / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)

    # 1. Base Python Binaries & DLLs
    for fn in ["python.exe", "pythonw.exe", "python3.dll", "python312.dll", "vcruntime140.dll", "vcruntime140_1.dll"]:
        src_file = PYTHON_BASE / fn
        if src_file.exists():
            shutil.copy2(src_file, runtime_dir / fn)

    log("Kopiere Python DLLs/...")
    shutil.copytree(PYTHON_BASE / "DLLs", runtime_dir / "DLLs")

    log("Kopiere Python Standard-Bibliothek (Lib/)...")
    def ignore_site_packages(folder, files):
        return ["site-packages", "__pycache__"] if "Lib" in folder else ["__pycache__"]

    shutil.copytree(PYTHON_BASE / "Lib", runtime_dir / "Lib", ignore=ignore_site_packages)

    log("Kopiere .venv Packages (PyTorch, Whisper, OpenCV, Flask) nach runtime/Lib/site-packages...")
    venv_site = PROJECT_ROOT / ".venv" / "Lib" / "site-packages"
    runtime_site = runtime_dir / "Lib" / "site-packages"
    
    def ignore_pyc(folder, files):
        return [f for f in files if f == "__pycache__" or f.endswith(".pyc")]

    shutil.copytree(venv_site, runtime_site, ignore=ignore_pyc)

def verify_portable_runtime():
    log("Verifiziere portables Python-Runtime...")
    import subprocess
    py_exe = STAGE_DIR / "runtime" / "python.exe"
    test_code = "import torch, cv2, faster_whisper, flask, yaml; print('PORTABLE RUNTIME VERIFIED!')"
    res = subprocess.run([str(py_exe), "-c", test_code], capture_output=True, text=True, cwd=str(STAGE_DIR))
    if res.returncode == 0 and "PORTABLE RUNTIME VERIFIED!" in res.stdout:
        log("SUCCESS: Portables Python startet einwandfrei und kann alle Module laden!")
    else:
        log(f"WARNING: Runtime-Test fehlgeschlagen:\nSTDOUT: {res.stdout}\nSTDERR: {res.stderr}")

def create_zip():
    log(f"Erstelle ZIP-Archiv: {ZIP_PATH} (dies kann 1-2 Minuten dauern)...")
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()

    total_files = sum(len(files) for _, _, files in os.walk(STAGE_DIR))
    processed = 0

    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for root, dirs, files in os.walk(STAGE_DIR):
            for file in files:
                full_path = Path(root) / file
                rel_path = full_path.relative_to(DIST_DIR)
                zf.write(full_path, arcname=str(rel_path))
                processed += 1
                if processed % 500 == 0 or processed == total_files:
                    pct = (processed / total_files) * 100
                    print(f"\r[PORTABLE BUILDER] Zippen: {processed}/{total_files} Dateien ({pct:.1f}%)...", end="", flush=True)

    print()
    size_mb = ZIP_PATH.stat().st_size / (1024 * 1024)
    size_gb = size_mb / 1024
    log(f"FERTIG! ZIP erfolgreich erstellt: {ZIP_PATH} ({size_gb:.2f} GB / {size_mb:.1f} MB)")

def main():
    log("=== START PORTABLE ZIP BUILD ===")
    clean_staging()
    copy_executable()
    copy_ffmpeg()
    copy_sources()
    copy_sanitized_config()
    setup_empty_folders()
    create_readme()
    build_portable_runtime()
    verify_portable_runtime()
    create_zip()
    log("=== PORTABLE ZIP BUILD ABGESCHLOSSEN ===")

if __name__ == "__main__":
    main()
