# ============================================================================
#  webrec Windows 설치 스크립트
#  PowerShell 에서 실행:  .\scripts\setup-windows.ps1
#  (실행이 막히면)      : powershell -ExecutionPolicy Bypass -File .\scripts\setup-windows.ps1
# ============================================================================
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot

function Has($name) { return [bool](Get-Command $name -ErrorAction SilentlyContinue) }

Write-Host ""
Write-Host "[1/4] 파이썬 확인" -ForegroundColor Cyan
if (Has "py")          { $py = "py -3" }
elseif (Has "python")  { $py = "python" }
else {
  Write-Host "  파이썬이 없습니다. 설치 후 다시 실행하세요." -ForegroundColor Red
  Write-Host "  winget install Python.Python.3.12" -ForegroundColor Yellow
  Write-Host "  (또는 https://www.python.org/downloads/ - 설치 시 'Add Python to PATH' 체크)"
  exit 1
}
Write-Host "  OK: $py"

Write-Host ""
Write-Host "[2/4] ffmpeg 확인 (녹화 엔진, 필수)" -ForegroundColor Cyan
if (Has "ffmpeg") {
  Write-Host "  OK: 이미 설치되어 있습니다."
} elseif (Has "winget") {
  Write-Host "  winget 으로 설치합니다..."
  winget install --id Gyan.FFmpeg -e --accept-package-agreements --accept-source-agreements
  Write-Host "  설치 후 PATH 반영을 위해 PowerShell 창을 새로 열어야 할 수 있습니다." -ForegroundColor Yellow
} else {
  Write-Host "  winget 이 없습니다. 아래에서 받아 PATH 에 추가하세요:" -ForegroundColor Red
  Write-Host "  https://www.gyan.dev/ffmpeg/builds/  (ffmpeg-release-essentials.zip)"
}

Write-Host ""
Write-Host "[3/4] 파이썬 패키지 설치" -ForegroundColor Cyan
Push-Location $root
iex "$py -m pip install --upgrade pip"
iex "$py -m pip install -r requirements.txt"
Write-Host "  Zoom 자동 입장을 위한 브라우저 설치..."
iex "$py -m playwright install chromium"
Pop-Location

Write-Host ""
Write-Host "[4/4] 준비 상태 점검" -ForegroundColor Cyan
Push-Location $root
iex "$py -m webrec doctor"
Pop-Location

Write-Host ""
Write-Host "설치가 끝났습니다. '예약녹화-시작.bat' 을 더블클릭하세요." -ForegroundColor Green
Write-Host ""
