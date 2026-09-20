@echo off
chcp 65001 >nul
cd /d "%~dp0"
title ChatGPT 월간 로그 자동화 - 설치

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install_task.ps1" 

echo.
pause
