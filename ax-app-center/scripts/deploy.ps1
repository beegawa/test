<#
.SYNOPSIS
  한 번 연결하고 01~05 단계를 순서대로 실행한다.
.DESCRIPTION
  -WhatIf: 연결하지 않고 각 단계의 실행 계획만 출력한다 (config 의 빈 값은 경고로만 표시).
  실제 실행: 테넌트 루트에 대화형 로그인 → 01(사이트) → 같은 인증으로 사이트에 연결 → 02~05.
  environment=prod 로 실행하려면 -ConfirmProd 를 함께 줘야 한다 (사람이 prod 로 바꾼 뒤에만).
.EXAMPLE
  ./deploy.ps1 -WhatIf -ConfigPath ../config/config.sample.json
  ./deploy.ps1
  ./deploy.ps1 -From 3          # 03-views 부터
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$ConfigPath,
    [ValidateRange(1, 5)][int]$From = 1,
    [ValidateRange(1, 5)][int]$To = 5,
    [switch]$ConfirmProd
)

. "$PSScriptRoot/lib/common.ps1"

$steps = @('01-site.ps1', '02-lists.ps1', '03-views.ps1', '04-permissions.ps1', '05-pages.ps1')

$planOnly = [bool]$WhatIfPreference
$cfg = Read-AxConfig -ConfigPath $ConfigPath -ForConnect:(-not $planOnly)
$cfgArg = @{ ConfigPath = $cfg.ConfigPath }

Write-AxStep "배포 ($($cfg.environment)) → $($cfg.SiteUrl)$(if ($planOnly) { '  [실행 계획만, 연결 안 함]' })"

if ($cfg.environment -eq 'prod' -and -not $planOnly -and -not $ConfirmProd) {
    throw 'environment=prod 입니다. 운영 배포는 사람이 확인한 뒤 -ConfirmProd 를 붙여 실행합니다.'
}

if (-not $planOnly) {
    Assert-AxSafeTarget -Config $cfg
    Connect-AxSite -Config $cfg -Url $cfg.TenantRootUrl
}

for ($n = $From; $n -le $To; $n++) {
    $script = Join-Path $PSScriptRoot $steps[$n - 1]
    # 02~05 는 사이트에 연결되어 있지 않으면 지금 인증을 재사용해 사이트로 옮긴다 (Initialize-AxStep)
    & $script @cfgArg -WhatIf:$planOnly
}

Write-Host ''
if ($planOnly) {
    Write-AxLog OK '실행 계획 출력 완료. 실제 실행은 -WhatIf 없이 config/config.json 으로 합니다.'
}
else {
    Write-AxLog OK "배포 완료. 다음: ./99-verify.ps1 로 점검$(if ($cfg.environment -eq 'test') { ', ./06-seed-test-data.ps1 로 등급 테스트 항목 생성' })"
}
