@echo off
setlocal
cd /d "%~dp0"
title ChatGPT 대화 로그 콘솔

echo.
echo   회사 ChatGPT 대화 로그 콘솔
echo   ------------------------------------------------
echo.

set "PY="
py -3 --version >nul 2>nul && set "PY=py -3"
if not defined PY (
  python --version >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo   [오류] 파이썬을 찾을 수 없습니다.
  echo          https://www.python.org/downloads/ 에서 설치한 뒤
  echo          이 파일을 다시 실행하세요.
  echo          설치 화면에서 Add python.exe to PATH 를 꼭 체크하세요.
  echo.
  pause
  exit /b 1
)

%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)"
if errorlevel 1 (
  echo   [오류] 파이썬 3.10 이상이 필요합니다. 설치된 버전:
  %PY% --version
  echo.
  pause
  exit /b 1
)

echo   [1/2] 필요한 패키지 확인 중...
%PY% -m pip install --quiet --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
  echo.
  echo   [오류] 패키지 설치에 실패했습니다.
  echo          아래 명령을 직접 실행해 보세요:
  echo.
  echo             %PY% -m pip install flask requests keyring openpyxl
  echo.
  echo          회사 PC 정책으로 막히면 --user 를 붙여 보세요.
  echo.
  pause
  exit /b 1
)

echo   [2/2] 웹 콘솔을 시작합니다. 브라우저가 자동으로 열립니다.
echo         이 창을 닫으면 프로그램이 종료됩니다.
echo.
%PY% app.py

echo.
echo   프로그램이 종료되었습니다.
pause
