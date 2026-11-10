@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [!] Virtuelle Umgebung noch nicht eingerichtet!
    echo [*] Fuehre zunaechst setup.bat aus...
    call setup.bat
)

call .venv\Scripts\activate.bat
python main.py %*
if %errorlevel% neq 0 (
    echo.
    echo [!] Programm beendet mit Fehlercode %errorlevel%.
    pause
)
