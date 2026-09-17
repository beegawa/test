@echo off
setlocal
cd /d "%~dp0"
title 자동 수집 등록

echo.
echo   ChatGPT 로그 자동 수집 등록
echo   ------------------------------------------------
echo   OpenAI 는 로그를 30일만 보관합니다. 그 전에 받아 두지 않으면
echo   영영 받을 수 없으므로, 매일 한 번 자동으로 받도록 등록합니다.
echo.
echo   등록할 작업: 매일 오전 3시 05분, 화면에 창을 띄우지 않고 조용히 수집
echo.

set "PY="
py -3 --version >nul 2>nul && set "PY=py -3"
if not defined PY (
  python --version >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo   [오류] 파이썬을 찾을 수 없습니다. 시작_Windows.bat 을 먼저 실행하세요.
  echo.
  pause
  exit /b 1
)

rem 창 없이 실행되는 pythonw.exe 경로를 찾는다
set "PYW="
for /f "usebackq delims=" %%P in (`%PY% -c "import os,sys;p=os.path.join(os.path.dirname(sys.executable),'pythonw.exe');print(p if os.path.isfile(p) else sys.executable)"`) do set "PYW=%%P"
if not defined PYW (
  echo   [오류] 파이썬 실행 파일을 찾지 못했습니다.
  echo.
  pause
  exit /b 1
)

schtasks /Create /TN "ChatGPT 로그 자동 수집" /F /SC DAILY /ST 03:05 ^
  /TR "\"%PYW%\" \"%~dp0collect.py\" --days 2 --quiet"
if errorlevel 1 (
  echo.
  echo   [오류] 작업 등록에 실패했습니다.
  echo          회사 PC 정책으로 막혔다면 관리자에게 문의하세요.
  echo          수동 등록: 작업 스케줄러에서 아래를 매일 실행하도록 만드세요.
  echo            프로그램: %PYW%
  echo            인수    : "%~dp0collect.py" --days 2 --quiet
  echo.
  pause
  exit /b 1
)

echo.
echo   등록했습니다. 이제 매일 자동으로 로그가 쌓입니다.
echo.
echo   확인/해제는 작업 스케줄러에서 "ChatGPT 로그 자동 수집" 을 보세요.
echo   지금 바로 한 번 돌려보려면 아무 키나 누르세요. (건너뛰려면 창을 닫으세요)
echo.
pause
%PY% collect.py --days 2
echo.
pause
