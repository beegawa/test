<#
.SYNOPSIS
  등급 판정 테스트 항목 7건을 등록부에 넣는다 (기획서 7.1). environment=test 에서만 동작한다.
.DESCRIPTION
  항목 제목은 '[TEST] <사례>' 이다. 같은 제목이 있으면 건너뛴다 (중복 생성 없음).
  -Refresh 를 주면 기존 테스트 항목의 입력 값을 표대로 다시 맞춘다 (테스트 항목만).
  결과 비교는 99-verify.ps1 이 한다.
  주의: 테스트 사이트에 흐름 F1이 연결되어 있으면 항목 생성 시 F1이 실행된다.
#>
[CmdletBinding(SupportsShouldProcess)]
param([string]$ConfigPath, [switch]$Refresh)

. "$PSScriptRoot/lib/common.ps1"

$ctx = Initialize-AxStep -ConfigPath $ConfigPath -WhatIf ([bool]$WhatIfPreference)
$cfg = $ctx.Config; $schema = $ctx.Schema
$listUrl = $schema.Lists.Registry.Url
Write-AxStep '06 테스트 데이터'

if ($cfg.environment -ne 'test') { throw "06-seed-test-data.ps1 은 environment=test 에서만 실행합니다. 현재 '$($cfg.environment)'." }
if ($cfg.SiteUrl -notmatch '-test$') { throw "안전 장치: 테스트 사이트가 아닙니다: $($cfg.SiteUrl)" }

$ch = $schema.Choices
function Get-AxTestValues {
    param([hashtable]$Case, [string]$Person)
    $sys = if ($Case.Core) { 'ERP' } else { '없음' }
    return @{
        Title            = $schema.TestPrefix + $Case.Title
        Purpose          = "등급 판정 테스트 항목. 기대 등급 $($Case.Expected)."
        Entity           = $ch.Entity[0].Label
        Dept             = 'GBI팀(테스트)'
        Developer        = $Person
        OwnerManager     = $Person
        AppType          = (Get-AxChoiceLabel -Choices $ch.AppType -Value '기타')
        UserScope        = (Get-AxChoiceLabel -Choices $ch.UserScope -Value $Case.Scope)
        HasInternalData  = [bool]$Case.Internal
        HasSensitiveData = [bool]$Case.Sensitive
        WritesToCore     = [bool]$Case.Core
        ConnectedSystems = [string[]]@(Get-AxChoiceLabel -Choices $ch.ConnectedSystems -Value $sys)
        RunLocation      = (Get-AxChoiceLabel -Choices $ch.RunLocation -Value '개인 PC')
    }
}

if ($ctx.PlanOnly) {
    foreach ($c in $schema.TestCases) {
        $v = Get-AxTestValues -Case $c -Person '<현재 사용자>'
        Write-AxLog PLAN ("항목 '{0}'  범위={1} 내부={2} 민감={3} ERP·MES입력={4}  기대 {5}" -f $v.Title, $v.UserScope, $c.Internal, $c.Sensitive, $c.Core, $c.Expected)
    }
    return
}

Assert-AxSafeTarget -Config $cfg
$me = Get-PnPProperty -ClientObject (Get-PnPWeb) -Property CurrentUser
$person = if ($me.Email) { $me.Email } else { $me.LoginName }

$existing = @{}
foreach ($it in Get-PnPListItem -List $listUrl -PageSize 500 -Fields 'Title') {
    $t = [string]$it['Title']
    if ($t.StartsWith($schema.TestPrefix)) { $existing[$t] = $it.Id }
}

foreach ($c in $schema.TestCases) {
    $v = Get-AxTestValues -Case $c -Person $person
    if ($existing.ContainsKey($v.Title)) {
        if ($Refresh -and $PSCmdlet.ShouldProcess($v.Title, 'Set-PnPListItem (입력 값 재설정)')) {
            Set-PnPListItem -List $listUrl -Identity $existing[$v.Title] -Values $v | Out-Null
            Write-AxLog CHANGE "테스트 항목 재설정: $($v.Title) (ID $($existing[$v.Title]))"
        }
        else { Write-AxLog SKIP "테스트 항목이 이미 있습니다: $($v.Title) (ID $($existing[$v.Title]))" }
        continue
    }
    if ($PSCmdlet.ShouldProcess($v.Title, 'Add-PnPListItem')) {
        $item = Add-PnPListItem -List $listUrl -Values $v
        Write-AxLog CHANGE "테스트 항목 추가: $($v.Title) (ID $($item.Id), 기대 $($c.Expected))"
    }
}
Write-AxLog OK '테스트 데이터 준비 완료. 99-verify.ps1 로 등급을 비교하세요.'
