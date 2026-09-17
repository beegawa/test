@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title ChatGPT 대화 로그 콘솔

echo.
echo   회사 ChatGPT 대화 로그 콘솔
echo   ------------------------------------------------
echo   [1/2] 필요한 패키지 확인
echo.

where py >nul 2>nul && (set PY=py -3) || (set PY=python)

%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" 2>nul
if errorlevel 1 (
  echo   파이썬 3.10 이상이 필요합니다.
  echo   https://www.python.org/downloads/ 에서 설치한 뒤 이 파일을 다시 실행하세요.
  echo   ^(설치 화면에서 "Add python.exe to PATH" 를 꼭 체크하세요^)
  pause
  exit /b 1
)

%PY% -m pip install --quiet --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
  echo   패키지 설치에 실패했습니다. 회사 PC 정책으로 막혔다면 관리자에게 문의하세요.
  pause
  exit /b 1
)

echo   [2/2] 웹 콘솔 시작 - 브라우저가 자동으로 열립니다
echo   이 창을 닫으면 종료됩니다.
echo.
%PY% app.py
pause
