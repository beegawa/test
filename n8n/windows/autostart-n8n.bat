@echo off
chcp 949 >nul 2>&1
setlocal

set "BASE=%USERPROFILE%\n8n"
set "ENVFILE=%BASE%\.env"
set "SRV=%BASE%\n8n-server.bat"
set "VBS=%BASE%\n8n-hidden.vbs"
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"

title n8n 자동 실행 설정

echo.
echo  ==================================================
echo    n8n 시작 + 부팅 시 자동 실행 설정
echo  ==================================================
echo.

if not exist "%ENVFILE%" goto NO_ENV
if not exist "%BASE%\logs" mkdir "%BASE%\logs"

rem ---- 이미 켜져 있는지 확인 ----
netstat -ano | findstr "LISTENING" | findstr ":5678" >nul
if not errorlevel 1 goto ALREADY_UP

rem ---- 1. 서버 실행 파일 생성 (.env 값을 그대로 박아넣음) ----
echo   [1/4] 서버 실행 파일 생성
>"%SRV%" echo @echo off
>>"%SRV%" echo rem 자동 생성됨 - autostart-n8n.bat
for /f "usebackq tokens=1,* delims==" %%a in ("%ENVFILE%") do (
  if not "%%a"=="" >>"%SRV%" echo set "%%a=%%b"
)
>>"%SRV%" echo cd /d "%BASE%"
>>"%SRV%" echo call n8n start ^>^> "%BASE%\logs\n8n.log" 2^>^&1

rem ---- 2. 창 없이 띄우는 실행기 ----
echo   [2/4] 백그라운드 실행기 생성
>"%VBS%" echo CreateObject("WScript.Shell").Run Chr(34) ^& "%SRV%" ^& Chr(34), 0, False

rem ---- 3. 시작프로그램 등록 ----
echo   [3/4] 부팅 시 자동 실행 등록
copy /y "%VBS%" "%STARTUP%\n8n-autostart.vbs" >nul
if errorlevel 1 goto NO_STARTUP
echo         등록됨: %STARTUP%\n8n-autostart.vbs

rem ---- 4. 지금 바로 실행 ----
echo   [4/4] n8n 시작 중... 최대 3분 기다립니다.
echo.
start "" wscript.exe "%VBS%"

set /a TRY=0
:WAIT
set /a TRY+=1
ping -n 4 127.0.0.1 >nul
netstat -ano | findstr "LISTENING" | findstr ":5678" >nul
if not errorlevel 1 goto UP
< nul set /p "=."
if %TRY% lss 60 goto WAIT
goto DOWN

:ALREADY_UP
echo   n8n 이 이미 실행 중입니다.
echo.
goto OPEN

:UP
echo.
echo.
echo  --------------------------------------------------
echo    n8n 실행됨. 창 없이 백그라운드에서 돌아갑니다.
echo.
echo    이제부터 PC 를 켜면 자동으로 시작됩니다.
echo    (자동 실행을 끄려면 아래 파일을 지우세요)
echo    %STARTUP%\n8n-autostart.vbs
echo  --------------------------------------------------

:OPEN
echo.
echo    브라우저를 엽니다: http://127.0.0.1:5678
echo.
start http://127.0.0.1:5678
echo    n8n 을 끄려면 작업관리자에서 node.exe 를 종료하세요.
echo.
pause
exit /b 0

:DOWN
echo.
echo.
echo  --------------------------------------------------
echo    3분이 지나도 5678 포트가 열리지 않았습니다.
echo    아래는 n8n 이 남긴 기록입니다.
echo  --------------------------------------------------
echo.
if exist "%BASE%\logs\n8n.log" (type "%BASE%\logs\n8n.log") else (echo    기록 파일이 없습니다.)
echo.
echo    이 내용을 보내주세요: %BASE%\logs\n8n.log
echo.
pause
exit /b 1

:NO_STARTUP
echo.
echo   [!] 시작프로그램 등록에 실패했습니다.
echo       (회사 보안정책으로 막혀 있을 수 있습니다)
echo       자동 실행 없이 지금 실행만 진행합니다.
echo.
start "" wscript.exe "%VBS%"
echo       잠시 후 http://127.0.0.1:5678 로 접속해 보세요.
echo.
pause
exit /b 0

:NO_ENV
echo   [!] %ENVFILE% 가 없습니다.
echo       install-n8n.bat 을 먼저 실행하세요.
echo.
pause
exit /b 1
