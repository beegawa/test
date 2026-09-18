@echo off
chcp 949 >nul 2>&1
setlocal

set "BASE=%USERPROFILE%\n8n"
set "LOG=%USERPROFILE%\Desktop\n8n-log2.txt"

rem ================= 서버 모드 (자기 자신을 다시 부름) =================
if "%~1"=="--server" goto SERVER

title n8n 기동 테스트

rem ---- .env 적용 ----
if not exist "%BASE%\.env" goto NO_ENV
for /f "usebackq tokens=1,* delims==" %%a in ("%BASE%\.env") do (
  if not "%%a"=="" set "%%a=%%b"
)

if exist "%LOG%" del "%LOG%"
echo ===================== 환경 =====================> "%LOG%"
echo 시각: %DATE% %TIME%>> "%LOG%"
node -v >> "%LOG%" 2>&1
call n8n --version >> "%LOG%" 2>&1
echo N8N_USER_FOLDER=%N8N_USER_FOLDER%>> "%LOG%"
echo N8N_PORT=%N8N_PORT%>> "%LOG%"
echo N8N_LISTEN_ADDRESS=%N8N_LISTEN_ADDRESS%>> "%LOG%"
echo.>> "%LOG%"
echo ============== n8n start 전체 출력 ==============>> "%LOG%"

echo.
echo  ==================================================
echo    n8n 기동 테스트
echo  ==================================================
echo.
echo   n8n 을 별도 창에서 시작하고, 뜰 때까지 기다립니다.
echo   최대 3분까지 기다립니다. 이 창을 닫지 마세요.
echo.

start "n8n server" /min "%~f0" --server

set /a TRY=0
echo   대기 중...

:WAIT
set /a TRY+=1
ping -n 4 127.0.0.1 >nul
netstat -ano | findstr "LISTENING" | findstr ":5678" >nul
if not errorlevel 1 goto UP
< nul set /p "=."
if %TRY% lss 60 goto WAIT
goto DOWN

:UP
echo.
echo.
echo  --------------------------------------------------
echo   성공. n8n 이 5678 포트에서 실행 중입니다.
echo   브라우저를 엽니다. 안 열리면 직접 접속하세요:
echo     http://127.0.0.1:5678
echo  --------------------------------------------------
echo.
echo   n8n 을 끄려면 최소화된 "n8n server" 창을 닫으세요.
echo.
start http://127.0.0.1:5678
pause
exit /b 0

:DOWN
echo.
echo.
echo  --------------------------------------------------
echo   3분이 지나도 5678 포트가 열리지 않았습니다.
echo   아래는 n8n 이 남긴 출력 전체입니다.
echo  --------------------------------------------------
echo.
type "%LOG%"
echo.
echo  --------------------------------------------------
echo   위 내용 = %LOG%
echo   이 파일을 그대로 보내주세요.
echo  --------------------------------------------------
echo.
pause
exit /b 1

:NO_ENV
echo.
echo   [!] %BASE%\.env 가 없습니다. install-n8n.bat 을 먼저 실행하세요.
echo.
pause
exit /b 1

rem ================= 실제 서버 =================
:SERVER
title n8n server
call n8n start >> "%LOG%" 2>&1
echo.>> "%LOG%"
echo [n8n 프로세스가 종료됨. exit code: %ERRORLEVEL%]>> "%LOG%"
exit /b
