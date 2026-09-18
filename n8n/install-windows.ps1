# n8n 설치 + 뉴스 클리핑 워크플로우 등록 (Windows PowerShell)
# 실행: 우클릭 > "PowerShell에서 실행"  또는  powershell -ExecutionPolicy Bypass -File install-windows.ps1
$ErrorActionPreference = 'Stop'
$Base = Join-Path $env:USERPROFILE 'n8n'

Write-Host '[1/4] Node.js 확인' -ForegroundColor Cyan
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
  Write-Host '  Node.js 가 없습니다. 설치를 시작합니다...' -ForegroundColor Yellow
  if (Get-Command winget -ErrorAction SilentlyContinue) {
    winget install -e --id OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements
    $env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')
  } else {
    Write-Host '  winget 이 없습니다. https://nodejs.org 에서 LTS 를 직접 설치한 뒤 다시 실행하세요.' -ForegroundColor Red
    exit 1
  }
}
Write-Host "  Node.js $(node -v)" -ForegroundColor Green

Write-Host '[2/4] n8n 설치 (수 분 소요)' -ForegroundColor Cyan
npm install -g n8n
Write-Host '  설치 완료' -ForegroundColor Green

Write-Host '[3/4] 실행 환경 구성' -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path "$Base\data","$Base\files","$Base\logs" | Out-Null
$EnvFile = Join-Path $Base '.env'
if (-not (Test-Path $EnvFile)) {
  $bytes = New-Object byte[] 32
  [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  $key = ($bytes | ForEach-Object { $_.ToString('x2') }) -join ''
  @"
N8N_USER_FOLDER=$Base\data
N8N_LISTEN_ADDRESS=127.0.0.1
N8N_PORT=5678
GENERIC_TIMEZONE=Asia/Seoul
TZ=Asia/Seoul
N8N_ENCRYPTION_KEY=$key
N8N_DEFAULT_BINARY_DATA_MODE=filesystem
N8N_DIAGNOSTICS_ENABLED=false
N8N_VERSION_NOTIFICATIONS_ENABLED=false
EXECUTIONS_DATA_PRUNE=true
EXECUTIONS_DATA_MAX_AGE=720
"@ | Set-Content -Path $EnvFile -Encoding UTF8
  Write-Host "  설정 파일 생성: $EnvFile" -ForegroundColor Green
} else {
  Write-Host "  기존 설정 유지: $EnvFile" -ForegroundColor Green
}

Get-Content $EnvFile | Where-Object { $_ -match '^\s*[^#].*=' } | ForEach-Object {
  $k,$v = $_ -split '=',2
  [Environment]::SetEnvironmentVariable($k.Trim(), $v.Trim(), 'Process')
}

Write-Host '[4/4] 워크플로우 등록' -ForegroundColor Cyan
$wf = Join-Path $PSScriptRoot 'workflows\daily-news-clipping.json'
n8n import:workflow --input="$wf"

Write-Host ''
Write-Host '완료. 아래 명령으로 n8n 을 실행하세요:' -ForegroundColor Green
Write-Host '  n8n start' -ForegroundColor White
Write-Host '실행 후 브라우저에서 http://localhost:5678 접속' -ForegroundColor White
