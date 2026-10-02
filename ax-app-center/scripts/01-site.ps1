<#
.SYNOPSIS
  1단계: 커뮤니케이션 사이트를 만든다 (기획서 5.1). 이미 있으면 건너뛴다.
.DESCRIPTION
  - environment=test 면 /sites/<alias>-test 에만 만든다.
  - 사이트 존재 확인은 테넌트 루트 연결로 대상 사이트의 REST(/_api/web)를 호출해 한다 (SharePoint 관리자 권한 불필요).
  - 끝나면 새 사이트로 연결을 옮겨 둔다 (deploy.ps1 이 이어서 02~05를 실행).
.EXAMPLE
  ./01-site.ps1 -WhatIf
#>
[CmdletBinding(SupportsShouldProcess)]
param([string]$ConfigPath)

. "$PSScriptRoot/lib/common.ps1"

$planOnly = [bool]$WhatIfPreference
$cfg = Read-AxConfig -ConfigPath $ConfigPath -ForConnect:(-not $planOnly)
Write-AxStep "01 사이트 ($($cfg.SiteUrl))"

if ($planOnly) {
    Write-AxLog PLAN "커뮤니케이션 사이트 확인/생성: $($cfg.SiteUrl)  제목='$($cfg.site.title)'  언어=$($cfg.site.lcid)  (M365 그룹 없음)"
    if ($cfg.MissingValues.Count) { Write-AxLog WARN ("실제 실행 전에 채울 값: " + ($cfg.MissingValues -join ', ')) }
    return
}

Assert-AxSafeTarget -Config $cfg

function Test-AxSiteExists {
    param([string]$Url)
    try {
        $null = Invoke-PnPSPRestMethod -Url "$Url/_api/web?`$select=Title" -ErrorAction Stop
        return $true
    }
    catch {
        $msg = $_.Exception.Message
        if ($msg -match '404|Not Found|찾을 수 없') { return $false }
        throw "사이트 존재 여부를 확인하지 못했습니다 ($Url): $msg"
    }
}

if (-not (Test-AxConnected)) { Connect-AxSite -Config $cfg -Url $cfg.TenantRootUrl }

if (Test-AxSiteExists -Url $cfg.SiteUrl) {
    Write-AxLog SKIP "사이트가 이미 있습니다: $($cfg.SiteUrl)"
}
elseif ($PSCmdlet.ShouldProcess($cfg.SiteUrl, 'New-PnPSite CommunicationSite')) {
    Assert-AxSafeTarget -Config $cfg -Url $cfg.SiteUrl
    $created = New-PnPSite -Type CommunicationSite -Title $cfg.site.title -Url $cfg.SiteUrl -Lcid ([uint32]$cfg.site.lcid)
    Write-AxLog CHANGE "사이트를 만들었습니다: $created"
    # 프로비저닝이 끝날 때까지 기다린다 (최대 약 5분)
    for ($i = 0; $i -lt 30; $i++) {
        if (Test-AxSiteExists -Url $cfg.SiteUrl) { break }
        Start-Sleep -Seconds 10
    }
}

Connect-AxSite -Config $cfg -Url $cfg.SiteUrl
$web = Get-PnPWeb -Includes Language, Title, WebTemplate
if ($web.Language -ne [uint32]$cfg.site.lcid) {
    Write-AxLog WARN "사이트 언어가 $($web.Language) 입니다 (설정 $($cfg.site.lcid)). 언어는 만든 뒤 바꿀 수 없습니다. 사람에게 확인을 요청하세요."
}
if ($web.WebTemplate -ne 'SITEPAGEPUBLISHING') {
    Write-AxLog WARN "사이트 템플릿이 $($web.WebTemplate) 입니다. 커뮤니케이션 사이트(SITEPAGEPUBLISHING)가 아닙니다."
}
if ($web.Title -ne $cfg.site.title -and $PSCmdlet.ShouldProcess($cfg.SiteUrl, "제목을 '$($cfg.site.title)'(으)로 변경")) {
    Set-PnPWeb -Title $cfg.site.title
    Write-AxLog CHANGE "사이트 제목 변경: '$($web.Title)' → '$($cfg.site.title)'"
}
Write-AxLog OK "사이트 준비 완료: $($cfg.SiteUrl)"
