import os
import shutil
import sys
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BASE_PYTHON = Path(r"C:\Users\rausc\AppData\Local\Programs\Python\Python312")
VENV_DIR = PROJECT_ROOT / ".venv"
RUNTIME_DIR = PROJECT_ROOT / "dist" / "runtime"

def prepare_runtime():
    print("=" * 60)
    print("🚀 Erstelle standalone portable Python 3.12 Runtime")
    print("=" * 60)

    if RUNTIME_DIR.exists():
        print(f"Lösche altes Runtime-Verzeichnis: {RUNTIME_DIR}")
        shutil.rmtree(RUNTIME_DIR)
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Copy Python binaries & core DLLs
    print("1. Kopiere Python-Binaries und DLLs...")
    for f in ["python.exe", "pythonw.exe", "python3.dll", "python312.dll", "vcruntime140.dll", "vcruntime140_1.dll"]:
        src = BASE_PYTHON / f
        if src.exists():
            shutil.copy2(src, RUNTIME_DIR / f)
            print(f"   ✓ {f}")

    # Copy DLLs directory
    dlls_target = RUNTIME_DIR / "DLLs"
    shutil.copytree(BASE_PYTHON / "DLLs", dlls_target)
    print(f"   ✓ DLLs/ ({len(list(dlls_target.glob('*')))} Dateien)")

    # 2. Copy Python Standard Library (filtered)
    print("2. Kopiere Standardbibliothek (Lib)...")
    lib_target = RUNTIME_DIR / "Lib"
    
    ignore_patterns = shutil.ignore_patterns(
        "site-packages", "__pycache__", "test", "tests",
        "idlelib", "turtledemo", "turtle.py"
    )
    shutil.copytree(BASE_PYTHON / "Lib", lib_target, ignore=ignore_patterns)
    print("   ✓ Lib/ (Standard-Bibliothek)")

    # 3. Copy Site-Packages from .venv (all required app packages)
    print("3. Kopiere App-Bibliotheken aus .venv...")
    sp_source = VENV_DIR / "Lib" / "site-packages"
    sp_target = lib_target / "site-packages"
    sp_target.mkdir(parents=True, exist_ok=True)

    total_pkgs = 0
    total_bytes = 0

    for item in sp_source.iterdir():
        name = item.name
        # Skip pycache (keep .dist-info/.egg-info because werkzeug & andere Pakete importlib.metadata.version() nutzen)
        if name == "__pycache__":
            continue
        
        # Skip the huge 1.95 GB nvidia cuda wheels (we include essential cublas/cudnn separately if desired)
        if name == "nvidia":
            print("   ℹ Überspringe riesige nvidia-Wheels (spart 1.95 GB)")
            continue

        target_item = sp_target / name
        if item.is_dir():
            shutil.copytree(
                item, target_item,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", "tests", "test")
            )
        else:
            shutil.copy2(item, target_item)
        
        total_pkgs += 1

    print(f"   ✓ {total_pkgs} Bibliotheken kopiert (Flask, OpenCV, Whisper, Playwright, etc.)")

    # 4. Measure Runtime Size
    total_size = sum(f.stat().st_size for f in RUNTIME_DIR.rglob("*") if f.is_file())
    print(f"\n📊 Gesamtgröße der standalone Runtime: {total_size / (1024*1024):.1f} MB")

    # 5. Verification Test
    print("\n4. Führe Selbsttest der standalone Runtime aus...")
    py_exe = RUNTIME_DIR / "python.exe"
    test_cmd = [
        str(py_exe), "-c",
        "import importlib.metadata, flask, werkzeug.serving, cv2, ctranslate2, yaml, requests, yt_dlp; "
        "assert importlib.metadata.version('werkzeug'); "
        "import src.web_studio; "
        "print('ALL_IMPORTS_SUCCESSFUL')"
    ]
    res = subprocess.run(test_cmd, capture_output=True, text=True, cwd=str(PROJECT_ROOT))
    if "ALL_IMPORTS_SUCCESSFUL" in res.stdout:
        print("   ✅ Selbsttest erfolgreich! Alle Module laden fehlerfrei.")
    else:
        print("   ❌ Fehler beim Selbsttest:")
        print("   STDOUT:", res.stdout)
        print("   STDERR:", res.stderr)
        sys.exit(1)

    print("=" * 60)
    print("🎉 Standalone Runtime bereit!")
    print("=" * 60)

if __name__ == "__main__":
    prepare_runtime()
