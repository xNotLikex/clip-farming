import os
import sys
import shutil
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

def find_iscc() -> Path:
    candidates = [
        Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
        Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
        Path(os.path.expandvars(r"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"))
    ]
    for c in candidates:
        if c.exists():
            return c
    raise FileNotFoundError("Inno Setup (ISCC.exe) nicht gefunden!")

def build():
    print("=" * 65)
    print("📦 ERSTELLE PROFESSIONELLEN CLIP-FARMING WINDOWS INSTALLER")
    print("=" * 65)

    iscc_path = find_iscc()
    print(f"✓ Inno Setup Compiler gefunden: {iscc_path}")

    # 1. Verify clip-farming.exe in target release
    target_exe = PROJECT_ROOT / "src-tauri" / "target" / "release" / "clip-farming.exe"
    if not target_exe.exists():
        raise FileNotFoundError(f"Binary nicht gefunden in {target_exe}. Bitte vorher 'cargo build --release' ausführen.")
    print(f"✓ Release-Binary vorhanden: {target_exe.name} ({target_exe.stat().st_size / (1024*1024):.1f} MB)")

    # 2. Verify FFmpeg in bin/
    ffmpeg_exe = PROJECT_ROOT / "bin" / "ffmpeg.exe"
    if not ffmpeg_exe.exists():
        sys_ffmpeg = shutil.which("ffmpeg") or r"C:\ffmpeg\bin\ffmpeg.exe"
        if Path(sys_ffmpeg).exists():
            (PROJECT_ROOT / "bin").mkdir(exist_ok=True)
            shutil.copy2(sys_ffmpeg, ffmpeg_exe)
            ffprobe_src = Path(sys_ffmpeg).parent / "ffprobe.exe"
            if ffprobe_src.exists():
                shutil.copy2(ffprobe_src, PROJECT_ROOT / "bin" / "ffprobe.exe")
            print("✓ FFmpeg in bin/ bereitgestellt")
        else:
            raise FileNotFoundError("FFmpeg nicht gefunden!")
    else:
        print("✓ FFmpeg & FFprobe in bin/ vorhanden")

    # 3. Verify Standalone Runtime
    runtime_dir = PROJECT_ROOT / "dist" / "runtime"
    if not runtime_dir.exists() or not (runtime_dir / "python.exe").exists():
        print("Runtime nicht gefunden. Erstelle standalone Runtime...")
        import prepare_standalone_runtime
        prepare_standalone_runtime.prepare_runtime()
    else:
        print("✓ Standalone Runtime in dist/runtime/ vorhanden")

    # 4. Clean previous installer
    out_dir = PROJECT_ROOT / "dist"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_setup = out_dir / "Clip-Farming-Installer.exe"
    if out_setup.exists():
        out_setup.unlink()

    # 5. Compile with Inno Setup
    iss_file = PROJECT_ROOT / "scripts" / "create_installer.iss"
    print(f"\nKompiliere Installer mit Inno Setup (LZMA2 Ultra-Kompression)...")
    print(f"Script: {iss_file.name}")
    print("Bitte warten (komprimiert ca. 750 MB Anwendungsdaten)...")

    res = subprocess.run([str(iscc_path), str(iss_file)], cwd=str(PROJECT_ROOT / "scripts"), capture_output=True, text=True)
    
    if res.returncode != 0:
        print("❌ Fehler beim Kompilieren mit Inno Setup:")
        print(res.stdout)
        print(res.stderr)
        sys.exit(1)

    if out_setup.exists():
        size_mb = out_setup.stat().st_size / (1024 * 1024)
        print("\n" + "=" * 65)
        print("🎉 INSTALLER ERFOLGREICH ERSTELLT!")
        print("=" * 65)
        print(f"📁 Datei:  {out_setup.name}")
        print(f"📊 Größe:  {size_mb:.1f} MB (Vollständig autark, inkl. Python & FFmpeg!)")
        print(f"📍 Pfad:   {out_setup}")
        print("=" * 65)
    else:
        print("❌ Setup-Datei wurde nicht im Zielordner gefunden!")

if __name__ == "__main__":
    build()
