@echo off
chcp 949 >nul 2>&1
setlocal
title n8n 실행 중

set "BASE=%USERPROFILE%\n8n"
set "ENVFILE=%BASE%\.env"

if not exist "%ENVFILE%" goto NOT_INSTALLED

for /f "usebackq tokens=1,* delims==" %%a in ("%ENVFILE%") do (
  if not "%%a"=="" set "%%a=%%b"
)

echo.
echo   n8n 을 시작합니다...
echo   브라우저에서 http://localhost:5678 로 접속하세요.
echo   끄려면 이 창에서 Ctrl+C 를 누르세요.
echo.
start "" /b cmd /c "ping -n 21 127.0.0.1 >nul & start http://localhost:5678"
call n8n start
echo.
echo   n8n 이 종료되었습니다.
pause
exit /b 0

:NOT_INSTALLED
echo.
echo   [!] 아직 설치되지 않았습니다.
echo       install-n8n.bat 을 먼저 실행해 주세요.
echo.
pause
exit /b 1
