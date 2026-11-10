@echo off
chcp 65001 >nul
echo ==============================================================================
echo [Clip-Farming Pipeline] - Portable Installer & Environment Setup
echo ==============================================================================

cd /d "%~dp0"

if not exist ".venv" (
    echo [*] Erstelle virtuelle Python-Umgebung (.venv)...
    python -m venv .venv
    if %errorlevel% neq 0 (
        echo [!] FEHLER: Python konnte nicht ausgefuehrt werden. Ist Python im PATH?
        pause
        exit /b %errorlevel%
    )
)

echo [*] Aktiviere Umgebung...
call .venv\Scripts\activate.bat

echo [*] Aktualisiere pip...
python -m pip install --upgrade pip

echo [*] Installiere PyTorch mit CUDA-Beschleunigung (fuer NVIDIA RTX GPU)...
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124

echo [*] Installiere restliche Abhaengigkeiten aus requirements.txt...
pip install -r requirements.txt

echo.
echo ==============================================================================
echo [OK] Setup erfolgreich abgeschlossen!
echo Starte die Pipeline jederzeit mit: run.bat
echo ==============================================================================
pause
