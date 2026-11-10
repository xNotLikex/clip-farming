@echo off
title Clip Farming Desktop (Rust & Tauri)
cd /d "%~dp0"

echo ========================================================
echo    CLIP FARMING - NATIVE WINDOWS DESKTOP APP (RUST)
echo ========================================================
echo.

if exist "src-tauri\target\debug\clip-farming.exe" (
    echo Starte Clip Farming Desktop App...
    start "" "src-tauri\target\debug\clip-farming.exe"
) else (
    echo Erstelle Desktop Build...
    cd src-tauri
    cargo run
)
