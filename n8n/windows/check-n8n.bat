@echo off
chcp 949 >nul 2>&1
setlocal
title n8n 진단

set "OUT=%USERPROFILE%\Desktop\n8n-check.txt"
set "BASE=%USERPROFILE%\n8n"

call :RUN > "%OUT%" 2>&1
type "%OUT%"
echo.
echo  --------------------------------------------------
echo   결과가 바탕화면에 저장되었습니다:
echo   %OUT%
echo   이 내용을 그대로 복사해서 보내주세요.
echo  --------------------------------------------------
echo.
pause
exit /b 0

:RUN
echo ===================== n8n 진단 =====================
echo 시각: %DATE% %TIME%
echo.

echo [1] Node.js
where node 2>&1
node -v 2>&1
echo.

echo [2] npm
call npm -v 2>&1
echo.

echo [3] n8n 설치 여부
where n8n 2>&1
if errorlevel 1 echo    ** n8n 명령을 찾을 수 없음 = 설치 실패 또는 PATH 미반영 **
echo.

echo [4] 실행 중인 node 프로세스
tasklist /fi "imagename eq node.exe" 2>&1
echo.

echo [5] 5678 포트 listen 상태
set "PORTOK=0"
netstat -ano | findstr "LISTENING" | findstr ":5678" && set "PORTOK=1"
if "%PORTOK%"=="0" echo    ** 5678 포트에서 대기 중인 프로그램 없음 = n8n 이 실행 중이 아님 **
echo.

echo [6] 설정 파일 (암호화 키는 숨김)
if exist "%BASE%\.env" (
  findstr /v /c:"N8N_ENCRYPTION_KEY" "%BASE%\.env"
  findstr /b /c:"N8N_ENCRYPTION_KEY" "%BASE%\.env" >nul && echo N8N_ENCRYPTION_KEY=***있음^(숨김^)***
) else (
  echo    ** %BASE%\.env 없음 = 설치가 3단계까지 가지 못함 **
)
echo.

echo [7] 데이터 폴더
if exist "%BASE%\data\.n8n" (dir /b "%BASE%\data\.n8n" 2>&1) else (echo    ** %BASE%\data\.n8n 없음 **)
echo.

echo [8] 워크플로우 등록 여부
if exist "%BASE%\data\.n8n\database.sqlite" (echo    database.sqlite 있음) else (echo    database.sqlite 없음 = n8n 이 한 번도 정상 기동하지 않음)
echo.

echo [9] 브라우저 프록시 설정 ^(사내망에서 localhost 가 막히는 원인^)
reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyEnable 2>&1
reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyServer 2>&1
reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyOverride 2>&1
echo.

echo [10] localhost 접속 테스트
powershell -NoProfile -Command "try{$r=Invoke-WebRequest -Uri 'http://127.0.0.1:5678/healthz' -UseBasicParsing -TimeoutSec 5; '  127.0.0.1 -> HTTP ' + $r.StatusCode + ' ' + $r.Content}catch{'  127.0.0.1 -> 실패: ' + $_.Exception.Message}" 2>&1
powershell -NoProfile -Command "try{$r=Invoke-WebRequest -Uri 'http://localhost:5678/healthz' -UseBasicParsing -TimeoutSec 5; '  localhost -> HTTP ' + $r.StatusCode + ' ' + $r.Content}catch{'  localhost -> 실패: ' + $_.Exception.Message}" 2>&1
echo.

echo ===================== 판정 =====================
if "%PORTOK%"=="1" (
  echo  n8n 은 실행 중입니다. 브라우저 쪽 문제일 가능성이 큽니다.
  echo  - 주소창에 http://127.0.0.1:5678 을 직접 입력해 보세요.
  echo  - 위 [9] 에서 ProxyEnable 이 0x1 이면 사내 프록시가 원인입니다.
) else (
  echo  n8n 이 실행 중이 아닙니다.
  echo  - install-n8n.bat 을 실행한 검은 창을 닫으셨다면 n8n 도 함께 종료됩니다.
  echo  - start-n8n.bat 을 더블클릭한 뒤, 창에
  echo    "Editor is now accessible via: http://localhost:5678"
  echo    이 뜰 때까지 기다렸다가 접속하세요. 처음에는 1~3분 걸립니다.
)
echo ===============================================
exit /b 0
