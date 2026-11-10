@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ==============================================================================
echo [Clip-Farming Studio] - Web Video Editor & Approval Dashboard
echo ==============================================================================

if not exist ".venv\Scripts\python.exe" (
    echo [!] Virtuelle Umgebung noch nicht eingerichtet! Fuehre setup.bat aus.
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat

echo [*] Starte Web Studio auf http://localhost:5000 ...
start http://localhost:5000
python -m src.web_studio

pause
