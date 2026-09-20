@echo off
chcp 65001 >nul
cd /d "%~dp0"
title ChatGPT 월간 로그 자동화 - 해제

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\uninstall_task.ps1" 

echo.
pause
