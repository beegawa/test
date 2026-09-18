@echo off
chcp 949 >nul 2>&1
setlocal
title n8n 설치 + 뉴스 클리핑 워크플로우

set "BASE=%USERPROFILE%\n8n"
set "HERE=%~dp0"
set "WF=%HERE%daily-news-clipping.json"

echo.
echo  ==================================================
echo    n8n 설치 + 매일 뉴스 클리핑 워크플로우 등록
echo  ==================================================
echo.

rem ---------- 1. Node.js ----------
echo  [1/5] Node.js 확인 중...
where node >nul 2>&1
if not errorlevel 1 goto NODE_OK

echo        Node.js 가 설치되어 있지 않습니다.
where winget >nul 2>&1
if errorlevel 1 goto NO_WINGET

echo        winget 으로 Node.js LTS 를 설치합니다. (수 분 소요)
winget install -e --id OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements
if exist "%ProgramFiles%\nodejs\node.exe" set "PATH=%ProgramFiles%\nodejs;%PATH%"
if exist "%ProgramFiles(x86)%\nodejs\node.exe" set "PATH=%ProgramFiles(x86)%\nodejs;%PATH%"
where node >nul 2>&1
if errorlevel 1 goto NODE_RESTART
goto NODE_OK

:NO_WINGET
echo.
echo        [!] winget 을 사용할 수 없습니다.
echo            https://nodejs.org 에서 LTS 버전을 내려받아 설치하신 뒤
echo            이 파일을 다시 실행해 주세요.
echo.
pause
exit /b 1

:NODE_RESTART
echo.
echo        [!] Node.js 는 설치됐지만 이 창에서 아직 인식되지 않습니다.
echo            이 창을 닫고 install-n8n.bat 을 다시 실행해 주세요.
echo.
pause
exit /b 1

:NODE_OK
for /f "delims=" %%v in ('node -v') do set "NODEVER=%%v"
echo        Node.js %NODEVER% 확인
echo.

rem ---------- 2. n8n ----------
echo  [2/5] n8n 설치 중... 5~10분 걸립니다. 창을 닫지 마세요.
call npm install -g n8n
if errorlevel 1 goto NPM_FAIL
echo        n8n 설치 완료
echo.

rem ---------- 3. 실행 환경 ----------
echo  [3/5] 실행 환경 구성 중...
if not exist "%BASE%\data"  mkdir "%BASE%\data"
if not exist "%BASE%\files" mkdir "%BASE%\files"
if not exist "%BASE%\logs"  mkdir "%BASE%\logs"

set "ENVFILE=%BASE%\.env"
if exist "%ENVFILE%" goto ENV_DONE

for /f "delims=" %%k in ('powershell -NoProfile -Command "[guid]::NewGuid().ToString('N')+[guid]::NewGuid().ToString('N')"') do set "KEY=%%k"
>"%ENVFILE%" echo N8N_USER_FOLDER=%BASE%\data
>>"%ENVFILE%" echo N8N_LISTEN_ADDRESS=127.0.0.1
>>"%ENVFILE%" echo N8N_PORT=5678
>>"%ENVFILE%" echo GENERIC_TIMEZONE=Asia/Seoul
>>"%ENVFILE%" echo TZ=Asia/Seoul
>>"%ENVFILE%" echo N8N_ENCRYPTION_KEY=%KEY%
>>"%ENVFILE%" echo N8N_DEFAULT_BINARY_DATA_MODE=filesystem
>>"%ENVFILE%" echo N8N_DIAGNOSTICS_ENABLED=false
>>"%ENVFILE%" echo N8N_VERSION_NOTIFICATIONS_ENABLED=false
>>"%ENVFILE%" echo EXECUTIONS_DATA_PRUNE=true
>>"%ENVFILE%" echo EXECUTIONS_DATA_MAX_AGE=720
echo        설정 파일 생성: %ENVFILE%
goto ENV_APPLY

:ENV_DONE
echo        기존 설정 사용: %ENVFILE%

:ENV_APPLY
set "N8N_USER_FOLDER=%BASE%\data"
set "N8N_LISTEN_ADDRESS=127.0.0.1"
set "N8N_PORT=5678"
set "GENERIC_TIMEZONE=Asia/Seoul"
set "TZ=Asia/Seoul"
set "N8N_DEFAULT_BINARY_DATA_MODE=filesystem"
set "N8N_DIAGNOSTICS_ENABLED=false"
set "N8N_VERSION_NOTIFICATIONS_ENABLED=false"
for /f "usebackq tokens=1,* delims==" %%a in ("%ENVFILE%") do (
  if "%%a"=="N8N_ENCRYPTION_KEY" set "N8N_ENCRYPTION_KEY=%%b"
)
echo.

rem ---------- 4. 워크플로우 등록 ----------
echo  [4/5] 워크플로우 등록 중...
if not exist "%WF%" goto NO_WF
call n8n import:workflow --input="%WF%"
if errorlevel 1 goto IMPORT_FAIL
echo        '매일 뉴스 클리핑 메일' 워크플로우 등록 완료
goto RUN

:NO_WF
echo.
echo        [!] daily-news-clipping.json 파일을 찾을 수 없습니다.
echo            이 bat 파일과 같은 폴더에 두고 다시 실행해 주세요.
echo            찾는 위치: %WF%
echo.
pause
exit /b 1

:IMPORT_FAIL
echo.
echo        [!] 워크플로우 등록에 실패했습니다.
echo            n8n 실행 후 화면에서 직접 Import 해도 됩니다.
echo.

rem ---------- 5. 실행 ----------
:RUN
echo.
echo  [5/5] n8n 을 시작합니다...
echo.
echo        잠시 후 브라우저가 자동으로 열립니다.
echo        열리지 않으면 직접 http://localhost:5678 로 접속하세요.
echo        n8n 을 끄려면 이 창에서 Ctrl+C 를 누르세요.
echo.
start "" /b cmd /c "ping -n 26 127.0.0.1 >nul & start http://localhost:5678"
call n8n start
goto END

:NPM_FAIL
echo.
echo        [!] n8n 설치에 실패했습니다.
echo            인터넷 연결을 확인하시고, 회사 네트워크라면
echo            프록시 설정이 필요할 수 있습니다.
echo.
pause
exit /b 1

:END
echo.
echo  n8n 이 종료되었습니다.
pause
