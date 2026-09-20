@echo off
chcp 65001 >nul
cd /d "%~dp0"
title ChatGPT 로그 수집 + 분석 (수동 실행)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_monthly.ps1" -Force -OpenReport

echo.
pause
