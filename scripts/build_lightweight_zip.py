"""
Clip Farming Studio - Lightweight Distribution Packager (~15-20 MB)
Erstellt ein schlankes, weitergabefähiges ZIP-Archiv OHNE private Daten
und OHNE riesige 1,5 GB Python/NVIDIA Pakete.
Auf dem Ziel-PC übernimmt die App mit 1 Klick die komplette Einrichtung!
"""

import os
import shutil
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = PROJECT_ROOT / "dist" / "Clip-Farming-Setup"
OUTPUT_ZIP = PROJECT_ROOT / "Clip-Farming-Setup.zip"

def build():
    print("=" * 60)
    print("🎬 Erstelle schlankes Clip-Farming Installationspaket (~18 MB)")
    print("=" * 60)

    # 1. Clean staging directory
    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
    DIST_DIR.mkdir(parents=True, exist_ok=True)

    # 2. Copy Executable
    exe_src = PROJECT_ROOT / "clip-farming.exe"
    if not exe_src.exists():
        exe_src = PROJECT_ROOT / "src-tauri" / "target" / "release" / "clip-farming.exe"
    
    if not exe_src.exists():
        raise FileNotFoundError(f"Binary nicht gefunden: {exe_src}")
    
    shutil.copy2(exe_src, DIST_DIR / "clip-farming.exe")
    print(f"✓ Binary kopiert: {exe_src.name} ({exe_src.stat().st_size / (1024*1024):.1f} MB)")

    # 3. Copy Batch Starters
    for bat in ["STARTEN.bat", "SETUP.bat"]:
        p = PROJECT_ROOT / bat
        if p.exists():
            shutil.copy2(p, DIST_DIR / bat)
            print(f"✓ Starter kopiert: {bat}")

    # 4. Copy Code Directories (Filtering out __pycache__)
    def copy_filtered(src_dir: Path, dst_dir: Path, ignore_patterns=None):
        if not src_dir.exists():
            return
        dst_dir.mkdir(parents=True, exist_ok=True)
        for root, dirs, files in os.walk(src_dir):
            dirs[:] = [d for d in dirs if d not in ["__pycache__", ".git", ".pytest_cache", "target"]]
            rel = Path(root).relative_to(src_dir)
            target_sub = dst_dir / rel
            target_sub.mkdir(parents=True, exist_ok=True)
            for f in files:
                if f.endswith((".pyc", ".pyo", ".tmp")):
                    continue
                shutil.copy2(Path(root) / f, target_sub / f)

    copy_filtered(PROJECT_ROOT / "src", DIST_DIR / "src")
    print("✓ Quellcode kopiert: src/")

    copy_filtered(PROJECT_ROOT / "ui", DIST_DIR / "ui")
    print("✓ Benutzeroberfläche kopiert: ui/ (inkl. setup.html)")

    copy_filtered(PROJECT_ROOT / "fonts", DIST_DIR / "fonts")
    print("✓ Schriften kopiert: fonts/")

    # 5. Copy Scripts (setup_pc.ps1)
    scripts_target = DIST_DIR / "scripts"
    scripts_target.mkdir(parents=True, exist_ok=True)
    setup_ps1 = PROJECT_ROOT / "scripts" / "setup_pc.ps1"
    if setup_ps1.exists():
        shutil.copy2(setup_ps1, scripts_target / "setup_pc.ps1")
        print("✓ Setup-Skript kopiert: scripts/setup_pc.ps1")

    # 6. Copy Requirements
    req_file = PROJECT_ROOT / "requirements.txt"
    if req_file.exists():
        shutil.copy2(req_file, DIST_DIR / "requirements.txt")
        print("✓ Requirements kopiert: requirements.txt")

    # 7. Create Clean Config Template (ZERO private tokens)
    config_dir = DIST_DIR / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    clean_config = """# Clip Farming Studio - Standardkonfiguration
hardware_encoder: "auto"
whisper_device: "auto"
whisper_model: "base"

streamers:
  - eliasn97
  - letshugotv
  - papaplatte
  - rewinside
  - trymacs
  - zarbex
  - nooreax

auto_publish: false
publish_interval_minutes: 30
"""
    with open(config_dir / "config.yaml", "w", encoding="utf-8") as f:
        f.write(clean_config)
    print("✓ Neutrale Konfiguration erstellt: config/config.yaml")

    # 8. Create README
    readme_content = """========================================================================
  CLIP FARMING STUDIO - SCHNELLEINSTIEG (PLUG & PLAY)
========================================================================

Willkommen beim Clip Farming Studio!

1. STARTE DIE APP:
   Mache einen Doppelklick auf 'clip-farming.exe'.

2. ERST-EINRICHTUNG:
   Beim ersten Start erkennt die App automatisch deine Grafikkarte
   (NVIDIA RTX/GeForce, AMD Radeon, Intel oder CPU) und richtet mit
   einem einzigen Klick alle benötigten KI- und Video-Module direkt
   in diesem Ordner ein.
   -> Dein Windows-System wird dabei NICHT verändert!

3. VIEL SPASS:
   Sobald die Einrichtung abgeschlossen ist, öffnet sich das Studio
   automatisch.

(Optional: Du kannst die Einrichtung auch vorab per Doppelklick auf
'SETUP.bat' starten.)
========================================================================
"""
    with open(DIST_DIR / "README.txt", "w", encoding="utf-8") as f:
        f.write(readme_content)
    print("✓ Anleitung erstellt: README.txt")

    # 9. Create Empty Directories
    for d in ["downloads", "output", "data"]:
        (DIST_DIR / d).mkdir(parents=True, exist_ok=True)

    # 10. Compress to ZIP
    print("\nKomprimiere Archiv...")
    if OUTPUT_ZIP.exists():
        OUTPUT_ZIP.unlink()

    with zipfile.ZipFile(OUTPUT_ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for root, _, files in os.walk(DIST_DIR):
            for file in files:
                p = Path(root) / file
                arcname = Path("Clip-Farming") / p.relative_to(DIST_DIR)
                zf.write(p, arcname)

    zip_size_mb = OUTPUT_ZIP.stat().st_size / (1024 * 1024)
    print(f"\n🎉 FERTIG! Archiv erfolgreich erstellt:")
    print(f"📦 Datei: {OUTPUT_ZIP.name}")
    print(f"📊 Größe: {zip_size_mb:.2f} MB (statt 1.500 MB!)")
    print(f"📁 Pfad:  {OUTPUT_ZIP}")
    print("=" * 60)

if __name__ == "__main__":
    build()
