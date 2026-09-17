@echo off
setlocal
cd /d "%~dp0"
title ChatGPT 대화 내용 받기

echo.
echo   ChatGPT 대화 내용 받기
echo   ------------------------------------------------
echo   최근 30일치 대화를 받아 엑셀로 만들고 바로 열어 드립니다.
echo   (웹 화면에 들어갈 필요 없습니다)
echo.

set "PY="
py -3 --version >nul 2>nul && set "PY=py -3"
if not defined PY (
  python --version >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo   [오류] 파이썬을 찾을 수 없습니다. 시작_Windows.bat 을 먼저 한 번 실행하세요.
  echo.
  pause
  exit /b 1
)

%PY% export_conversations.py
if errorlevel 2 (
  echo.
  echo   관리자 키가 없습니다. 시작_Windows.bat 으로 키를 먼저 저장하세요.
)
echo.
pause
