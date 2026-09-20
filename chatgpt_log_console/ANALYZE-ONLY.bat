@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 이미 받은 로그만 다시 분석

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_monthly.ps1" -Force -SkipDownload -OpenReport

echo.
pause
