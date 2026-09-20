#Requires -Version 5.1
<#
.SYNOPSIS
    등록된 "매달 말일 수집·분석" 작업을 제거한다. (받아둔 파일과 리포트는 지우지 않는다)
#>
[CmdletBinding()]
param([string] $TaskName = 'ChatGPT-Monthly-Log-Report')

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

$removed = $false
if (Get-Command Unregister-ScheduledTask -ErrorAction SilentlyContinue) {
    try {
        Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop | Out-Null
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        $removed = $true
    } catch { }
}
if (-not $removed) {
    & schtasks.exe /Delete /TN $TaskName /F | Out-Null
    $removed = ($LASTEXITCODE -eq 0)
}

if ($removed) {
    Write-Host "  [완료] '$TaskName' 작업을 제거했습니다. 받아둔 로그와 리포트는 그대로 있습니다." -ForegroundColor Green
} else {
    Write-Host "  등록된 '$TaskName' 작업이 없습니다." -ForegroundColor Yellow
}
Write-Host ""
