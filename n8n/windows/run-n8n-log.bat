@echo off
chcp 949 >nul 2>&1
setlocal
title n8n 실행 + 오류 기록

set "BASE=%USERPROFILE%\n8n"
set "LOG=%USERPROFILE%\Desktop\n8n-log.txt"

echo.
echo  ==================================================
echo    n8n 을 실행하고 모든 출력을 기록합니다
echo  ==================================================
echo.
echo   기록 파일: %LOG%
echo.

rem ---- .env 적용 ----
if not exist "%BASE%\.env" goto NO_ENV
for /f "usebackq tokens=1,* delims==" %%a in ("%BASE%\.env") do (
  if not "%%a"=="" set "%%a=%%b"
)
goto ENV_OK

:NO_ENV
echo   [!] %BASE%\.env 가 없습니다. install-n8n.bat 을 먼저 실행하세요.
echo.
pause
exit /b 1

:ENV_OK
if not exist "%BASE%\data" mkdir "%BASE%\data"

rem ---- 1단계: 로딩 단계에서 죽는지 확인 ----
echo ===== 환경 =====> "%LOG%"
echo N8N_USER_FOLDER=%N8N_USER_FOLDER%>> "%LOG%"
echo N8N_PORT=%N8N_PORT%>> "%LOG%"
echo N8N_LISTEN_ADDRESS=%N8N_LISTEN_ADDRESS%>> "%LOG%"
node -v >> "%LOG%" 2>&1
echo.>> "%LOG%"
echo ===== n8n --version =====>> "%LOG%"

echo   [1/2] n8n 로딩 확인 중... (30초 정도 걸릴 수 있습니다)
call n8n --version >> "%LOG%" 2>&1
set "RC=%ERRORLEVEL%"
echo exit code: %RC%>> "%LOG%"
echo.>> "%LOG%"

echo.
echo   --- 결과 ---
type "%LOG%"
echo   ------------
echo.

if not "%RC%"=="0" goto LOAD_FAIL

rem ---- 2단계: 실제 기동 ----
echo   [2/2] n8n 을 시작합니다.
echo.
echo   "Editor is now accessible via: http://localhost:5678" 가 보이면 성공입니다.
echo   그때 브라우저에서 http://127.0.0.1:5678 로 접속하세요.
echo   처음에는 1~3분 걸립니다. 이 창을 닫지 마세요.
echo.
echo   (오류로 바로 종료되면 그 내용이 기록 파일에 남습니다)
echo.
echo ===== n8n start =====>> "%LOG%"
powershell -NoProfile -Command "& { n8n start 2>&1 | Tee-Object -FilePath ($env:USERPROFILE + '\Desktop\n8n-log.txt') -Append }"

echo.
echo  --------------------------------------------------
echo   n8n 이 종료되었습니다.
echo   기록 파일을 그대로 복사해 보내주세요: %LOG%
echo  --------------------------------------------------
echo.
pause
exit /b 0

:LOAD_FAIL
echo  --------------------------------------------------
echo   n8n 이 로딩 단계에서 실패했습니다.
echo   위 내용과 %LOG% 파일을 그대로 복사해 보내주세요.
echo  --------------------------------------------------
echo.
pause
exit /b 1
