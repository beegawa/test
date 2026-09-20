#Requires -Version 5.1
<#
.SYNOPSIS
    "매달 말일 수집·분석"을 Windows 작업 스케줄러에 등록한다.

.DESCRIPTION
    작업 스케줄러에는 매일 실행으로 등록하고, 말일인지 여부는 run_monthly.ps1 이 판단한다.
    이렇게 하면 말일에 PC 가 꺼져 있었더라도 다음에 켤 때 지난달분을 자동으로 따라잡는다.
    관리자 권한은 필요 없으며, 로그인한 사용자 계정으로 등록된다.
#>
[CmdletBinding()]
param(
    [string] $Time     = '09:00',
    [string] $TaskName = 'ChatGPT-Monthly-Log-Report'
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

$Base   = Split-Path -Parent $PSScriptRoot
$Runner = Join-Path $PSScriptRoot 'run_monthly.ps1'
$Desc   = "매달 말일 09시 기준으로 대화내용_받기.BAT 를 실행하고 로그를 분석해 HTML 리포트를 만듭니다. (폴더: $Base)"

if (-not (Test-Path $Runner)) { throw "run_monthly.ps1 을 찾을 수 없습니다: $Runner" }
if ($Time -notmatch '^\d{1,2}:\d{2}$') { throw "시각 형식이 잘못되었습니다: $Time  (예: 09:00)" }

$settingsPath = Join-Path $Base 'settings.json'
if (Test-Path $settingsPath) {
    try {
        $cfg = Get-Content $settingsPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($cfg.taskTime -and $PSBoundParameters.Keys -notcontains 'Time') { $Time = $cfg.taskTime }
        if ($cfg.taskName -and $PSBoundParameters.Keys -notcontains 'TaskName') { $TaskName = $cfg.taskName }
    } catch { }
}

$psExe  = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$psArgs = "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$Runner`""

Write-Host ""
Write-Host "  작업 이름 : $TaskName"
Write-Host "  실행 시각 : 매일 $Time 확인 → 말일에만 실제 수집·분석 (놓친 달은 자동 보충)"
Write-Host "  대상 폴더 : $Base"
Write-Host ""

$registered = $false
if (Get-Command Register-ScheduledTask -ErrorAction SilentlyContinue) {
    try {
        $action   = New-ScheduledTaskAction -Execute $psExe -Argument $psArgs -WorkingDirectory $Base
        $hh, $mm  = $Time.Split(':')
        $at       = (Get-Date -Hour ([int]$hh) -Minute ([int]$mm) -Second 0)
        $trigger  = New-ScheduledTaskTrigger -Daily -At $at
        $taskSet  = New-ScheduledTaskSettingsSet -StartWhenAvailable `
                        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
                        -MultipleInstances IgnoreNew `
                        -ExecutionTimeLimit (New-TimeSpan -Hours 6)
        Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
                               -Settings $taskSet -Description $Desc -Force | Out-Null
        $registered = $true
    } catch {
        Write-Warning "PowerShell 방식 등록 실패 → schtasks 로 다시 시도합니다. ($($_.Exception.Message))"
    }
}

if (-not $registered) {
    $tr = "`"$psExe`" $psArgs"
    & schtasks.exe /Create /TN $TaskName /TR $tr /SC DAILY /ST $Time /F | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "작업 스케줄러 등록에 실패했습니다. (schtasks 코드 $LASTEXITCODE)" }
    $registered = $true
}

Write-Host "  [완료] 작업이 등록되었습니다." -ForegroundColor Green
try {
    $info = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop | Get-ScheduledTaskInfo
    Write-Host ("  다음 실행 예정 : {0}" -f $info.NextRunTime)
} catch {
    & schtasks.exe /Query /TN $TaskName /FO LIST | Select-String 'Next Run Time|다음 실행 시간'
}

# 분석에 필요한 파이썬이 있는지 미리 확인한다 (없으면 말일에 가서야 실패한다)
$pyFound = $false
foreach ($name in @('py', 'python', 'python3')) {
    if (Get-Command $name -ErrorAction SilentlyContinue) { $pyFound = $true; break }
}
Write-Host ""
if ($pyFound) {
    Write-Host "  · 분석에 쓸 파이썬을 찾았습니다." -ForegroundColor Green
} else {
    Write-Host "  [주의] 파이썬이 없습니다. 분석 단계에서 실패합니다." -ForegroundColor Yellow
    Write-Host "         https://www.python.org/downloads/ 에서 설치할 때 'Add python.exe to PATH' 를 꼭 체크하세요."
    Write-Host "         이미 설치되어 있다면 settings.json 의 pythonExe 에 python.exe 전체 경로를 적어 주세요."
}
Write-Host "  · PC 가 켜져 있고 로그인된 상태에서 실행됩니다. 꺼져 있었다면 다음 로그인 때 보충 실행됩니다."
Write-Host "  · 바로 한 번 돌려 보려면 '지금-수집분석.bat' 을 실행하세요."
Write-Host ""
