@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 예약 녹화 (webrec)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1"

echo.
echo  프로그램이 종료되었습니다.
pause
