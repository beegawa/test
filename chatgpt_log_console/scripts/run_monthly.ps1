#Requires -Version 5.1
<#
.SYNOPSIS
    매달 말일에 대화내용_받기.BAT 를 실행하고, 받아진 로그를 분석해 HTML 리포트를 만든다.

.DESCRIPTION
    Windows 작업 스케줄러가 매일 이 스크립트를 부르고, 스크립트가 "오늘이 말일인가"를 판단한다.
    말일에 PC 가 꺼져 있어 건너뛴 경우에는 다음 실행 때 지난달분을 자동으로 따라잡는다.

.PARAMETER Force
    말일이 아니어도, 이미 처리한 달이어도 그냥 실행한다.
.PARAMETER SkipDownload
    받기 BAT 는 실행하지 않고 이미 있는 파일만 분석한다.
.PARAMETER Period
    분석할 달을 직접 지정한다. (예: 2026-09)
.PARAMETER OpenReport
    끝나면 리포트를 브라우저로 연다. (수동 실행용)
#>
[CmdletBinding()]
param(
    [switch] $Force,
    [switch] $SkipDownload,
    [string] $Period,
    [switch] $OpenReport
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

$Base      = Split-Path -Parent $PSScriptRoot
$StartedAt = Get-Date

# ---------------------------------------------------------------- 설정
$defaults = @{
    downloadBat             = '대화내용_받기.BAT'
    downloadTimeoutMinutes  = 120
    reportDir               = 'reports'
    logDir                  = 'logs'
    stateDir                = '.state'
    pythonExe               = ''
    keepLogDays             = 365
}
$settings = $defaults.Clone()
$settingsPath = Join-Path $Base 'settings.json'
if (Test-Path $settingsPath) {
    try {
        $json = Get-Content -Path $settingsPath -Raw -Encoding UTF8 | ConvertFrom-Json
        foreach ($p in $json.PSObject.Properties) {
            if ($null -ne $p.Value -and $p.Value -ne '') { $settings[$p.Name] = $p.Value }
        }
    } catch {
        Write-Warning "settings.json 을 읽지 못해 기본값으로 진행합니다: $($_.Exception.Message)"
    }
}

$LogDir    = Join-Path $Base $settings.logDir
$ReportDir = Join-Path $Base $settings.reportDir
$StateDir  = Join-Path $Base $settings.stateDir
foreach ($d in @($LogDir, $ReportDir, $StateDir)) {
    if (-not (Test-Path $d)) { New-Item -ItemType Directory -Path $d -Force | Out-Null }
}
$LogFile = Join-Path $LogDir ("run_{0:yyyyMMdd_HHmmss}.log" -f $StartedAt)

function Write-Log {
    param([string] $Message, [string] $Level = 'INFO')
    $line = "{0:yyyy-MM-dd HH:mm:ss} [{1}] {2}" -f (Get-Date), $Level, $Message
    switch ($Level) {
        'ERROR' { Write-Host $line -ForegroundColor Red }
        'WARN'  { Write-Host $line -ForegroundColor Yellow }
        default { Write-Host $line }
    }
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

function Save-State {
    param([hashtable] $State)
    ($State | ConvertTo-Json -Depth 4) | Set-Content -Path (Join-Path $StateDir 'state.json') -Encoding UTF8
}

function Exit-With {
    param([int] $Code, [string] $Message, [string] $Level = 'ERROR')
    Write-Log $Message $Level
    Write-Log ("종료 (코드 {0}, 소요 {1:n1}분)" -f $Code, ((Get-Date) - $StartedAt).TotalMinutes)
    exit $Code
}

# ---------------------------------------------------------------- 실행 대상 월 판정
$today     = Get-Date
$lastOfMon = [DateTime]::DaysInMonth($today.Year, $today.Month)
$isLastDay = ($today.Day -eq $lastOfMon)
if ($Period) {
    $target = $Period
} elseif ($isLastDay) {
    $target = $today.ToString('yyyy-MM')              # 말일 당일 → 이번 달
} else {
    $target = $today.AddDays(-$today.Day).ToString('yyyy-MM')   # 그 외 → 지난달(따라잡기)
}

$statePath = Join-Path $StateDir 'state.json'
$state = @{ lastCompletedPeriod = ''; lastRunAt = ''; lastReport = ''; completedPeriods = @() }
if (Test-Path $statePath) {
    try {
        $s = Get-Content -Path $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
        foreach ($p in $s.PSObject.Properties) { $state[$p.Name] = $p.Value }
    } catch { }
}
$done = @($state.completedPeriods) | Where-Object { $_ }
if ($done.Count -eq 0 -and $state.lastCompletedPeriod) { $done = @($state.lastCompletedPeriod) }

Write-Log "=== ChatGPT 월간 로그 수집·분석 시작 ==="
Write-Log "폴더: $Base"
Write-Log ("오늘 {0:yyyy-MM-dd} · 이번 달 말일 {1}일 · 분석 대상 {2}" -f $today, $lastOfMon, $target)

if (-not $Force -and ($done -contains $target)) {
    Write-Log "$target 은 이미 처리했습니다. (마지막 실행 $($state.lastRunAt)) 건너뜁니다." 'INFO'
    exit 0
}
if (-not $Force -and -not $isLastDay -and [string]::IsNullOrEmpty($Period)) {
    Write-Log "말일에 실행하지 못한 $target 분을 따라잡습니다." 'WARN'
}

# ---------------------------------------------------------------- 1) 받기 BAT 실행
$dataExt = @('.sqlite', '.sqlite3', '.db', '.db3', '.json', '.jsonl', '.ndjson', '.csv', '.zip')
$skipRe  = '\\(reports|logs|scripts|\.state|\.git)\\'

function Get-DataSnapshot {
    $map = @{}
    Get-ChildItem -Path $Base -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $dataExt -contains $_.Extension.ToLower() -and $_.FullName -notmatch $skipRe -and $_.Name -ne 'settings.json' } |
        ForEach-Object { $map[$_.FullName] = "$($_.Length)|$($_.LastWriteTimeUtc.Ticks)" }
    return $map
}

$before = Get-DataSnapshot
if ($SkipDownload) {
    Write-Log "-SkipDownload 지정 → 받기 BAT 를 건너뜁니다."
} else {
    $bat = Join-Path $Base $settings.downloadBat
    if (-not (Test-Path $bat)) {
        Exit-With 2 "받기 파일을 찾을 수 없습니다: $bat  (settings.json 의 downloadBat 을 확인하세요)"
    }
    $outLog = Join-Path $LogDir ("download_{0:yyyyMMdd_HHmmss}.log" -f $StartedAt)
    $errLog = "$outLog.err"
    Write-Log "받기 실행: $bat  (최대 $($settings.downloadTimeoutMinutes)분 대기)"
    $proc = Start-Process -FilePath $env:ComSpec -ArgumentList '/c', "`"$bat`"" `
                          -WorkingDirectory $Base -NoNewWindow -PassThru `
                          -RedirectStandardOutput $outLog -RedirectStandardError $errLog
    $null = $proc.Handle   # ExitCode 를 읽으려면 핸들을 먼저 잡아둬야 한다
    $timeoutMs = [int] ([double] $settings.downloadTimeoutMinutes * 60 * 1000)
    if (-not $proc.WaitForExit($timeoutMs)) {
        # cmd.exe 만 죽이면 실제 내려받기 프로세스가 남으므로 자식까지 함께 정리한다
        try { & taskkill.exe /PID $proc.Id /T /F 2>&1 | Out-Null } catch { }
        try { if (-not $proc.HasExited) { $proc.Kill() } } catch { }
        Exit-With 6 "받기가 $($settings.downloadTimeoutMinutes)분 안에 끝나지 않아 중단했습니다. 로그: $outLog"
    }
    if ($proc.ExitCode -ne 0) {
        Write-Log "받기 BAT 가 0이 아닌 코드($($proc.ExitCode))로 끝났습니다. 로그: $outLog" 'WARN'
    } else {
        Write-Log "받기 완료 (로그: $outLog)"
    }
    if ((Test-Path $errLog) -and (Get-Item $errLog).Length -gt 0) {
        Write-Log "받기 표준오류 출력이 있습니다: $errLog" 'WARN'
    }
}

# ---------------------------------------------------------------- 2) 새로 받아진 파일 확인
$after = Get-DataSnapshot
$fresh = @($after.Keys | Where-Object { $before[$_] -ne $after[$_] })
if ($fresh.Count -gt 0) {
    Write-Log "새로 받아진(또는 갱신된) 파일 $($fresh.Count)개:"
    foreach ($f in $fresh) { Write-Log ("  - {0} ({1:n1} MB)" -f $f, ((Get-Item $f).Length / 1MB)) }
} elseif ($after.Count -gt 0) {
    Write-Log "새로 받아진 파일이 없습니다. 폴더에 있는 기존 파일 $($after.Count)개로 분석합니다." 'WARN'
} else {
    Exit-With 4 "분석할 로그 파일이 폴더에 없습니다. 받기 로그를 확인하세요: $LogDir"
}

# ---------------------------------------------------------------- 3) 파이썬 찾기
function Find-Python {
    if ($settings.pythonExe -and (Test-Path $settings.pythonExe)) { return @($settings.pythonExe) }
    $candidates = @()
    $candidates += , @('py', '-3')
    $candidates += , @('python')
    $candidates += , @('python3')
    foreach ($cand in $candidates) {
        try {
            $cmd = Get-Command $cand[0] -ErrorAction Stop
            $extra = @()
            if ($cand.Count -gt 1) { $extra = $cand[1..($cand.Count - 1)] }
            $global:LASTEXITCODE = 0
            & $cmd.Source @extra '--version' 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) { return @($cmd.Source) + $extra }
        } catch { }
    }
    return $null
}

$py = @(Find-Python)
if ($py.Count -eq 0) {
    Exit-With 3 ("파이썬을 찾지 못했습니다. https://www.python.org/downloads/ 에서 설치하거나 " +
                 "settings.json 의 pythonExe 에 python.exe 경로를 적어 주세요.")
}
Write-Log "파이썬: $($py -join ' ')"

# ---------------------------------------------------------------- 4) 분석
$analyzer = Join-Path $PSScriptRoot 'analyze_logs.py'
if (-not (Test-Path $analyzer)) { Exit-With 7 "분석 스크립트가 없습니다: $analyzer" }

Write-Log "분석 시작 (대상 월 $target)"
$exe = $py[0]
$pyArgs = @()
if ($py.Count -gt 1) { $pyArgs += $py[1..($py.Count - 1)] }
$pyArgs += @($analyzer, '--base', $Base, '--period', $target, '--out', $ReportDir)

$env:PYTHONIOENCODING = 'utf-8'
$output = & $exe @pyArgs 2>&1
$code = $LASTEXITCODE
foreach ($line in $output) { Write-Log ("  " + $line) }

if ($code -ne 0) {
    Exit-With $code "분석이 실패했습니다. (코드 $code) 위 로그를 확인하세요."
}

$reportLine = $output | Where-Object { $_ -match '^REPORT=' } | Select-Object -Last 1
$report = if ($reportLine) { ($reportLine -replace '^REPORT=', '').Trim() } else { '' }

# ---------------------------------------------------------------- 5) 마무리
$state.lastCompletedPeriod = $target
$state.lastRunAt = $StartedAt.ToString('yyyy-MM-dd HH:mm:ss')
$state.lastReport = $report
$state.completedPeriods = @(@($done + $target) | Select-Object -Unique | Sort-Object | Select-Object -Last 24)
Save-State $state

if ($settings.keepLogDays -gt 0) {
    Get-ChildItem -Path $LogDir -File -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(- [int]$settings.keepLogDays) } |
        Remove-Item -Force -ErrorAction SilentlyContinue
}

Write-Log "리포트: $report"
Write-Log ("=== 완료 (소요 {0:n1}분) ===" -f ((Get-Date) - $StartedAt).TotalMinutes)

if ($OpenReport -and $report -and (Test-Path $report)) {
    Start-Process $report
}
exit 0
