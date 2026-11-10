@echo off
chcp 65001 >nul
title Clip Farming - Automatische Einrichtung

echo ====================================================================
echo  CLIP FARMING STUDIO - AUTOMATISCHE ERST-EINRICHTUNG
echo ====================================================================
echo.
echo Dieses Skript richtet Python, FFmpeg und alle KI-Module
echo vollautomatisch im Programmordner ein.
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup_pc.ps1"

echo.
echo ====================================================================
echo  EINRICHTUNG ABGESCHLOSSEN!
echo ====================================================================
echo Du kannst das Programm jetzt mit "clip-farming.exe" starten!
echo.
pause
