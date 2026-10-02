# AX 앱 센터 공통 함수: 설정 읽기, 연결, 로깅, 멱등 헬퍼.
# 모든 단계 스크립트가 dot-source 한다:  . "$PSScriptRoot/lib/common.ps1"
#
# 원칙 (CLAUDE.md 참고)
#  - 멱등: 대상이 있으면 건너뛰거나 갱신한다. 지우고 다시 만들지 않는다.
#  - 삭제 없음: 사이트·목록·열·항목을 지우는 코드는 넣지 않는다.
#  - test 환경에서는 URL 끝이 -test 인 사이트에만 쓴다.
#  - 비밀 값 없음: 대화형 로그인만 쓴다.

Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'

$script:AxRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$script:AxLogFile = $null

. (Join-Path $PSScriptRoot 'schema.ps1')

#region 로깅

function Write-AxLog {
    param(
        [ValidateSet('INFO', 'OK', 'SKIP', 'CHANGE', 'PLAN', 'WARN', 'ERROR')]
        [string]$Level = 'INFO',
        [Parameter(Mandatory)][string]$Message
    )
    $color = @{ INFO = 'Gray'; OK = 'Green'; SKIP = 'DarkGray'; CHANGE = 'Cyan'; PLAN = 'Magenta'; WARN = 'Yellow'; ERROR = 'Red' }[$Level]
    $line = '{0} [{1,-6}] {2}' -f (Get-Date -Format 'HH:mm:ss'), $Level, $Message
    Write-Host $line -ForegroundColor $color
    if (-not $script:AxLogFile) {
        $dir = Join-Path $script:AxRoot 'logs'
        if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -WhatIf:$false | Out-Null }
        $script:AxLogFile = Join-Path $dir ('run-{0}.log' -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
    }
    Add-Content -Path $script:AxLogFile -Value $line -Encoding utf8 -WhatIf:$false
}

function Write-AxStep {
    param([Parameter(Mandatory)][string]$Title)
    Write-Host ''
    Write-AxLog INFO "===== $Title ====="
}

#endregion

#region 설정

function Test-AxPlaceholder {
    # '<...>' 형태의 자리 표시 값이면 true
    param([AllowNull()][object]$Value)
    if ($null -eq $Value) { return $true }
    $s = [string]$Value
    return ([string]::IsNullOrWhiteSpace($s) -or $s -match '^<.*>$')
}

function Get-AxConfigPath {
    param([string]$ConfigPath)
    if ($ConfigPath) { return (Resolve-Path $ConfigPath).Path }
    $p = Join-Path $script:AxRoot 'config/config.json'
    if (-not (Test-Path $p)) {
        throw "config/config.json 이 없습니다. config/config.sample.json 을 복사해 값을 채우세요. (실행 계획만 보려면 -ConfigPath config/config.sample.json -WhatIf)"
    }
    return $p
}

function Read-AxConfig {
    <#
      설정을 읽고 검증한 뒤 계산 값(SiteUrl 등)을 붙여 돌려준다.
      -ForConnect 면 연결에 필요한 값(tenant, clientId)과 사람 값이 비어 있을 때 멈춘다.
    #>
    param([string]$ConfigPath, [switch]$ForConnect)

    $path = Get-AxConfigPath $ConfigPath
    $cfg = Get-Content -Path $path -Raw -Encoding utf8 | ConvertFrom-Json -AsHashtable

    foreach ($k in 'environment', 'tenant', 'site', 'people', 'entities', 'review', 'labels') {
        if (-not $cfg.ContainsKey($k)) { throw "config: '$k' 항목이 없습니다 ($path)" }
    }
    if ($cfg.environment -notin @('test', 'prod')) { throw "config: environment 는 'test' 또는 'prod' 여야 합니다. 현재 '$($cfg.environment)'" }
    if (-not $cfg.ContainsKey('clientId')) { $cfg.clientId = '' }
    if (-not $cfg.ContainsKey('permissions')) { $cfg.permissions = @{} }
    if (-not $cfg.permissions.ContainsKey('visitorsCanSubmit')) { $cfg.permissions.visitorsCanSubmit = $false }

    $alias = $cfg.site.alias
    if ($alias -notmatch '^[a-z0-9-]+$') { throw "config: site.alias 는 영문 소문자, 숫자, '-' 만 씁니다. 현재 '$alias'" }
    if ($cfg.environment -eq 'test' -and $alias -notmatch '-test$') { $alias = "$alias-test" }
    if ($cfg.environment -eq 'prod' -and $alias -match '-test$') { throw "config: environment 가 prod 인데 site.alias 가 -test 로 끝납니다." }

    $cfg.SiteAlias = $alias
    $cfg.TenantRootUrl = "https://$($cfg.tenant).sharepoint.com"
    $cfg.SiteUrl = "$($cfg.TenantRootUrl)/sites/$alias"
    $cfg.SiteServerRelativeUrl = "/sites/$alias"
    $cfg.ConfigPath = $path

    # 사람이 정할 값(9장)이 비어 있는지 모아 둔다.
    $missing = [System.Collections.Generic.List[string]]::new()
    if (Test-AxPlaceholder $cfg.tenant) { $missing.Add('tenant') }
    if (Test-AxPlaceholder $cfg.clientId) { $missing.Add('clientId (IT가 PnP 앱 등록 후 전달)') }
    if (@($cfg.entities | Where-Object { -not (Test-AxPlaceholder $_) }).Count -eq 0 -or
        @($cfg.entities | Where-Object { Test-AxPlaceholder $_ }).Count -gt 0) { $missing.Add('entities (D2)') }
    if (@($cfg.people.owners | Where-Object { Test-AxPlaceholder $_ }).Count -gt 0 -or @($cfg.people.owners).Count -eq 0) { $missing.Add('people.owners (D4)') }
    if (@($cfg.people.reviewers | Where-Object { Test-AxPlaceholder $_ }).Count -gt 0) { $missing.Add('people.reviewers (D4)') }
    if (Test-AxPlaceholder $cfg.people.securityApprover) { $missing.Add('people.securityApprover (D4)') }
    foreach ($k in 'ERP', 'MES', 'default') {
        if (Test-AxPlaceholder $cfg.people.systemApprovers[$k]) { $missing.Add("people.systemApprovers.$k (D4)") }
    }
    $cfg.MissingValues = $missing.ToArray()

    if ($ForConnect -and $missing.Count -gt 0) {
        $list = ($missing | ForEach-Object { "  - $_" }) -join "`n"
        throw "config 에 사람이 정할 값이 비어 있습니다. 추측해서 채우지 않습니다. 다음 값을 채운 뒤 다시 실행하세요:`n$list`n(파일: $path, 기획서 9장 참고)"
    }
    return $cfg
}

function Assert-AxSafeTarget {
    # test 환경에서는 -test 사이트에만 쓴다. 쓰기 전에 매번 호출한다.
    param([Parameter(Mandatory)][hashtable]$Config, [string]$Url = $Config.SiteUrl)
    if ($Config.environment -eq 'test' -and $Url.TrimEnd('/') -notmatch '-test$') {
        throw "안전 장치: environment=test 인데 대상 URL이 -test 로 끝나지 않습니다: $Url"
    }
}

function Get-AxAllPeople {
    # 검토자 그룹에 넣을 사람: 법인 AX 담당자 + 보안 + 시스템 담당 (중복 제거)
    param([Parameter(Mandatory)][hashtable]$Config)
    $p = $Config.people
    $all = @($p.reviewers) + @($p.securityApprover) + @($p.systemApprovers.Values)
    return @($all | Where-Object { -not (Test-AxPlaceholder $_) } | ForEach-Object { $_.Trim().ToLowerInvariant() } | Sort-Object -Unique)
}

#endregion

#region 연결

function Assert-AxPnPModule {
    if (-not (Get-Module -ListAvailable -Name PnP.PowerShell)) {
        throw "PnP.PowerShell 모듈이 없습니다. 'Install-Module PnP.PowerShell -Scope CurrentUser' 로 설치하세요. (PowerShell 7.4.0 이상 필요)"
    }
    if ($PSVersionTable.PSVersion -lt [version]'7.4.0') {
        throw "PowerShell 7.4.0 이상이 필요합니다. 현재 $($PSVersionTable.PSVersion)"
    }
    Import-Module PnP.PowerShell -ErrorAction Stop
}

function Connect-AxSite {
    <#
      대화형 로그인으로 연결한다. 이미 연결되어 있으면 그 인증을 재사용해 대상 URL로 옮긴다.
      clientId 가 비어 있으면 멈추고 안내한다 (앱 등록은 IT가 한 번만 한다).
    #>
    param([Parameter(Mandatory)][hashtable]$Config, [Parameter(Mandatory)][string]$Url)

    if (Test-AxPlaceholder $Config.clientId) {
        throw @"
config.json 의 clientId 가 비어 있습니다. 멈춥니다.
PnP PowerShell용 Entra ID 앱 등록은 IT가 한 번만 합니다 (2024-09-09부터 테넌트별 자체 등록 필수):
  Register-PnPEntraIDAppForInteractiveLogin -ApplicationName "PnP.PowerShell" -Tenant $($Config.tenant).onmicrosoft.com
등록 후 받은 Application(client) ID를 config.json 의 clientId 에 넣으세요. 이 스크립트는 앱 등록을 시도하지 않습니다.
"@
    }
    Assert-AxPnPModule

    $current = $null
    try { $current = Get-PnPConnection -ErrorAction Stop } catch { $current = $null }

    if ($current -and $current.Url.TrimEnd('/') -eq $Url.TrimEnd('/')) {
        return
    }
    if ($current) {
        Write-AxLog INFO "연결 전환: $Url (기존 인증 재사용)"
        Connect-PnPOnline -Url $Url -Interactive -Connection $current
    }
    else {
        Write-AxLog INFO "대화형 로그인: $Url"
        Connect-PnPOnline -Url $Url -Interactive -ClientId $Config.clientId
    }
}

function Test-AxConnected {
    param([string]$Url)
    try {
        $c = Get-PnPConnection -ErrorAction Stop
        if ($Url) { return ($c.Url.TrimEnd('/') -eq $Url.TrimEnd('/')) }
        return $true
    }
    catch { return $false }
}

function Initialize-AxStep {
    <#
      단계 스크립트 공통 시작 처리.
      반환: @{ Config; Schema; PlanOnly }
      - WhatIf 이면 연결하지 않고 실행 계획만 출력하도록 PlanOnly = $true
      - deploy.ps1 이 이미 사이트에 연결했으면 그대로 쓴다.
    #>
    param([string]$ConfigPath, [bool]$WhatIf, [switch]$SiteMustExist)

    $planOnly = $WhatIf
    $cfg = Read-AxConfig -ConfigPath $ConfigPath -ForConnect:(-not $planOnly)
    $schema = Get-AxSchema -Config $cfg
    if (-not $planOnly) {
        Assert-AxSafeTarget -Config $cfg
        if (-not (Test-AxConnected -Url $cfg.SiteUrl)) { Connect-AxSite -Config $cfg -Url $cfg.SiteUrl }
    }
    return @{ Config = $cfg; Schema = $schema; PlanOnly = $planOnly }
}

#endregion

#region 멱등 헬퍼

function Get-AxListOrNull {
    param([Parameter(Mandatory)][string]$Url)
    return (Get-PnPList -Identity $Url -ErrorAction SilentlyContinue)
}

function Get-AxRoleNames {
    # 역할 이름은 사이트 언어로 번역되어 있다 (예: '읽기'). RoleTypeKind 로 찾아 실제 이름을 돌려준다.
    $map = @{}
    foreach ($rd in Get-PnPRoleDefinition) {
        $kind = [string]$rd.RoleTypeKind
        if ($kind -and $kind -ne 'None' -and -not $map.ContainsKey($kind)) { $map[$kind] = $rd.Name }
    }
    foreach ($k in 'Administrator', 'Editor', 'Reader', 'Contributor') {
        if (-not $map.ContainsKey($k)) { throw "역할 정의를 찾지 못했습니다: $k" }
    }
    return $map
}

function ConvertTo-AxXmlText {
    param([AllowEmptyString()][string]$Text)
    return [System.Security.SecurityElement]::Escape($Text)
}

#endregion
