# =============================================================================
#  webrec - 필요한 프로그램을 자동으로 설치하고 예약 녹화 화면을 띄운다.
#  보통은 '예약녹화-시작.bat' 을 더블클릭하면 이 스크립트가 실행된다.
# =============================================================================
[CmdletBinding()]
param([switch]$SkipStart, [switch]$CheckOnly)

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Write-Step([string]$label, [string]$text) {
    Write-Host ""
    Write-Host "[$label] $text" -ForegroundColor Cyan
}
function Write-Ok([string]$text)   { Write-Host "  OK   $text" -ForegroundColor Green }
function Write-Warn2([string]$text) { Write-Host "  주의 $text" -ForegroundColor Yellow }
function Write-Err([string]$text)  { Write-Host "  실패 $text" -ForegroundColor Red }
function Have([string]$name) { return [bool](Get-Command $name -ErrorAction SilentlyContinue) }

# ----------------------------------------------------------------- 파이썬
function Find-Python {
    # py 실행기 (권장)
    if (Have 'py') {
        try {
            $version = & py -3 --version 2>&1
            if ("$version" -match 'Python 3') { return 'py -3' }
        } catch { }
    }
    # python.exe (단, 마이크로소프트 스토어 안내용 가짜 파일은 제외)
    if (Have 'python') {
        try {
            $version = & python --version 2>&1
            if ("$version" -match 'Python 3') { return 'python' }
        } catch { }
    }
    # PATH 에 없더라도 기본 설치 위치를 찾아본다.
    # 환경변수가 비어 있으면 경로가 루트가 되어 디스크 전체를 훑게 되므로 걸러낸다.
    $bases = @()
    if ($env:LOCALAPPDATA) { $bases += "$env:LOCALAPPDATA\Programs\Python" }
    if ($env:ProgramFiles) { $bases += "$env:ProgramFiles\Python*" }
    $bases += 'C:\Python3*'
    foreach ($base in $bases) {
        if (-not (Test-Path (Split-Path -Parent $base) -ErrorAction SilentlyContinue)) { continue }
        $found = Get-ChildItem -Path $base -Filter 'python.exe' -Recurse -Depth 2 -ErrorAction SilentlyContinue |
                 Sort-Object FullName -Descending | Select-Object -First 1
        if ($found) { return $found.FullName }
    }
    return $null
}

function Install-Python {
    if (-not (Have 'winget')) {
        Write-Err "파이썬이 없고 winget 도 없어 자동 설치를 할 수 없습니다."
        Write-Host "  아래 주소에서 직접 설치한 뒤 이 창을 다시 실행하세요:" -ForegroundColor Yellow
        Write-Host "    https://www.python.org/downloads/"
        Write-Host "  설치 화면에서 'Add Python to PATH' 를 꼭 체크하세요." -ForegroundColor Yellow
        try { Start-Process "https://www.python.org/downloads/" } catch { }
        return $null
    }
    Write-Host "  파이썬을 설치합니다. 몇 분 걸릴 수 있습니다..."
    winget install --id Python.Python.3.12 -e --silent --scope user `
        --accept-package-agreements --accept-source-agreements | Out-Null
    return (Find-Python)
}

# ------------------------------------------------------------------ ffmpeg
function Find-Ffmpeg {
    if (Have 'ffmpeg') { return (Get-Command ffmpeg).Source }
    $candidates = @(
        "$root\tools\ffmpeg\bin\ffmpeg.exe",
        "$env:LOCALAPPDATA\Microsoft\WinGet\Links\ffmpeg.exe",
        "C:\ffmpeg\bin\ffmpeg.exe",
        "$env:ProgramData\chocolatey\bin\ffmpeg.exe",
        "$env:USERPROFILE\scoop\shims\ffmpeg.exe"
    )
    foreach ($path in $candidates) {
        if (Test-Path $path) { return $path }
    }
    if ($env:LOCALAPPDATA) {
        $winget = "$env:LOCALAPPDATA\Microsoft\WinGet\Packages"
        if (Test-Path $winget) {
            $found = Get-ChildItem -Path $winget -Filter 'ffmpeg.exe' -Recurse -Depth 4 -ErrorAction SilentlyContinue |
                     Select-Object -First 1
            if ($found) { return $found.FullName }
        }
    }
    return $null
}

function Install-Ffmpeg {
    if (Have 'winget') {
        Write-Host "  winget 으로 ffmpeg 를 설치합니다. 몇 분 걸릴 수 있습니다..."
        winget install --id Gyan.FFmpeg -e --silent `
            --accept-package-agreements --accept-source-agreements | Out-Null
        $found = Find-Ffmpeg
        if ($found) { return $found }
        Write-Warn2 "winget 설치를 확인하지 못했습니다. 직접 내려받아 봅니다."
    }

    # winget 이 없거나 실패하면 압축 파일을 받아 프로그램 폴더에 풀어둔다
    $zipUrl = 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip'
    $toolsDir = Join-Path $root 'tools'
    $zipPath = Join-Path $toolsDir 'ffmpeg.zip'
    try {
        New-Item -ItemType Directory -Force -Path $toolsDir | Out-Null
        Write-Host "  ffmpeg 를 내려받는 중입니다 (약 80MB)..."
        $ProgressPreference = 'SilentlyContinue'
        Invoke-WebRequest -Uri $zipUrl -OutFile $zipPath -UseBasicParsing
        Write-Host "  압축을 푸는 중..."
        Expand-Archive -Path $zipPath -DestinationPath $toolsDir -Force
        Remove-Item $zipPath -ErrorAction SilentlyContinue
        $extracted = Get-ChildItem -Path $toolsDir -Directory |
                     Where-Object { $_.Name -like 'ffmpeg-*' } | Select-Object -First 1
        if ($extracted) {
            $target = Join-Path $toolsDir 'ffmpeg'
            if (Test-Path $target) { Remove-Item $target -Recurse -Force -ErrorAction SilentlyContinue }
            Move-Item $extracted.FullName $target
        }
        return (Find-Ffmpeg)
    } catch {
        Write-Err "ffmpeg 자동 설치에 실패했습니다: $($_.Exception.Message)"
        Write-Host "  직접 받아 C:\ffmpeg 에 풀어주세요: $zipUrl" -ForegroundColor Yellow
        return $null
    }
}

# ================================================================== 진행
Write-Host ""
Write-Host "==============================================================" -ForegroundColor White
Write-Host "  예약 녹화 - 준비 및 시작" -ForegroundColor White
Write-Host "==============================================================" -ForegroundColor White

Write-Step "1/4" "파이썬 확인"
$py = Find-Python
if (-not $py) {
    Write-Warn2 "파이썬이 없습니다. 설치를 시작합니다."
    $py = Install-Python
}
if (-not $py) {
    Write-Host ""
    Write-Host "파이썬 설치 후 이 파일을 다시 실행해 주세요." -ForegroundColor Red
    Read-Host "엔터를 누르면 닫힙니다"
    exit 1
}
# 'py -3' 처럼 인자가 붙는 경우를 실행파일과 인자로 나눠 둔다.
# (조건부 $() 로 인자를 만들면 PowerShell 5.1 에서 빈 인자가 섞여 들어간다)
if ($py -like 'py *') { $pyExe = 'py'; $pyArgs = @('-3') }
else                  { $pyExe = $py; $pyArgs = @() }
Write-Ok "파이썬: $py"

Write-Step "2/4" "ffmpeg 확인 (녹화 엔진, 필수)"
$ffmpeg = Find-Ffmpeg
if (-not $ffmpeg) {
    Write-Warn2 "ffmpeg 가 없습니다. 설치를 시작합니다."
    $ffmpeg = Install-Ffmpeg
}
if ($ffmpeg) {
    Write-Ok "ffmpeg: $ffmpeg"
    # 이번 실행에서 프로그램이 찾을 수 있도록 PATH 에 넣어준다
    $binDir = Split-Path -Parent $ffmpeg
    if ($env:Path -notlike "*$binDir*") { $env:Path = "$binDir;$env:Path" }
    $env:WEBREC_FFMPEG = $ffmpeg
    $probe = Join-Path $binDir 'ffprobe.exe'
    if (Test-Path $probe) { $env:WEBREC_FFPROBE = $probe }
} else {
    Write-Err "ffmpeg 없이는 녹화할 수 없습니다."
    Read-Host "엔터를 누르면 닫힙니다"
    exit 1
}

Write-Step "3/4" "파이썬 패키지 확인"
$needsInstall = $true
try {
    & $pyExe @pyArgs -c "import yaml" 2>$null
    if ($LASTEXITCODE -eq 0) { $needsInstall = $false }
} catch { }

if ($needsInstall) {
    Write-Host "  필요한 패키지를 설치합니다..."
    & $pyExe @pyArgs -m pip install --upgrade pip --disable-pip-version-check -q
    & $pyExe @pyArgs -m pip install -r requirements.txt --disable-pip-version-check -q
    if ($LASTEXITCODE -ne 0) {
        Write-Err "패키지 설치에 실패했습니다. 인터넷 연결을 확인해 주세요."
        Read-Host "엔터를 누르면 닫힙니다"
        exit 1
    }
    # Zoom 자동 입장용 브라우저 (없어도 녹화는 되므로 실패해도 넘어간다)
    & $pyExe @pyArgs -m playwright install chromium 2>$null | Out-Null
    Write-Ok "패키지 설치 완료"
} else {
    Write-Ok "이미 설치되어 있습니다"
}

Write-Step "4/4" "준비 상태 점검"
& $pyExe @pyArgs -m webrec doctor

if ($CheckOnly) { exit 0 }
if ($SkipStart) { exit 0 }

Write-Host ""
Write-Host "==============================================================" -ForegroundColor Green
Write-Host "  예약 녹화 화면을 엽니다: http://127.0.0.1:8765" -ForegroundColor Green
Write-Host "  * 녹화가 끝날 때까지 이 창을 닫지 마세요 *" -ForegroundColor Yellow
Write-Host "  끝내려면 Ctrl+C" -ForegroundColor Green
Write-Host "==============================================================" -ForegroundColor Green
Write-Host ""

& $pyExe @pyArgs -m webrec serve --open
