@echo off
chcp 65001 >nul
title 예약 녹화 (webrec)
cd /d "%~dp0"

set "PY=python"
where py >nul 2>nul
if %errorlevel%==0 set "PY=py -3"

echo.
echo  ============================================================
echo    예약 녹화 프로그램을 시작합니다
echo    잠시 후 브라우저가 열립니다: http://127.0.0.1:8765
echo.
echo    * 녹화 시간까지 이 창을 닫지 마세요 *
echo    끝내려면 이 창에서 Ctrl+C 를 누르거나 창을 닫으세요.
echo  ============================================================
echo.

%PY% -m webrec serve --open

echo.
if errorlevel 1 (
  echo  [오류] 실행하지 못했습니다.
  echo.
  echo   1) 파이썬이 설치되어 있나요?   python --version
  echo      없다면: https://www.python.org/downloads/ 에서 설치
  echo      (설치할 때 "Add Python to PATH" 를 꼭 체크하세요^)
  echo.
  echo   2) 처음 실행이라면 setup-windows.ps1 을 먼저 실행하세요.
  echo      PowerShell 에서:  .\scripts\setup-windows.ps1
  echo.
)
pause
