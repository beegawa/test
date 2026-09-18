@echo off
chcp 949 >nul 2>&1
setlocal

set "BASE=%USERPROFILE%\n8n"
set "WF=%~dp0daily-news-clipping.json"
set "LOG=%USERPROFILE%\Desktop\n8n-import.txt"

title 뉴스 클리핑 워크플로우 등록

echo.
echo  ==================================================
echo    뉴스 클리핑 워크플로우 자동 등록
echo  ==================================================
echo.

if not exist "%WF%" goto NO_WF
if not exist "%BASE%\.env" goto NO_ENV

for /f "usebackq tokens=1,* delims==" %%a in ("%BASE%\.env") do (
  if not "%%a"=="" set "%%a=%%b"
)

echo   등록 중입니다. 30초 정도 걸립니다. 창을 닫지 마세요.
echo.

call n8n import:workflow --input="%WF%" > "%LOG%" 2>&1
set "RC=%ERRORLEVEL%"

findstr /i /c:"Successfully imported" "%LOG%" >nul
if not errorlevel 1 goto OK
goto FAIL

:OK
echo  --------------------------------------------------
echo    등록 완료.
echo.
echo    브라우저로 돌아가서 F5 로 새로고침하세요.
echo    좌측 Overview 에 "매일 뉴스 클리핑 메일" 이 보입니다.
echo  --------------------------------------------------
echo.
pause
exit /b 0

:FAIL
echo  --------------------------------------------------
echo    등록 실패 (exit code %RC%)
echo  --------------------------------------------------
echo.
type "%LOG%"
echo.
echo    n8n 서버가 켜져 있어서 충돌했을 수 있습니다.
echo    "n8n server" 창을 닫고 이 파일을 다시 실행해 보세요.
echo    그래도 안 되면 위 내용을 보내주세요.
echo    기록: %LOG%
echo.
pause
exit /b 1

:NO_WF
echo   [!] daily-news-clipping.json 을 찾을 수 없습니다.
echo       이 bat 파일과 같은 폴더에 두고 다시 실행하세요.
echo       찾는 위치: %WF%
echo.
pause
exit /b 1

:NO_ENV
echo   [!] %BASE%\.env 가 없습니다.
echo       install-n8n.bat 을 먼저 실행하세요.
echo.
pause
exit /b 1
