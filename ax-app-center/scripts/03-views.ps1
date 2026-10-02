<#
.SYNOPSIS
  5단계: 프로그램 등록부의 보기 6개 (기획서 5.3 보기). 기본 보기는 카탈로그.
.DESCRIPTION
  보기는 영문 키(Catalog, ReviewQueue ...)로 만들어 URL을 영문(Catalog.aspx)으로 두고, 제목만 한국어로 바꾼다.
  다시 실행하면 URL로 찾아 열·조건·제목을 맞춘다. 기존 'All Items' 등 다른 보기는 건드리지 않는다.
#>
[CmdletBinding(SupportsShouldProcess)]
param([string]$ConfigPath)

. "$PSScriptRoot/lib/common.ps1"

$ctx = Initialize-AxStep -ConfigPath $ConfigPath -WhatIf ([bool]$WhatIfPreference)
$cfg = $ctx.Config; $schema = $ctx.Schema
$listUrl = $schema.Lists.Registry.Url
Write-AxStep "03 보기 ($listUrl)"

if ($ctx.PlanOnly) {
    foreach ($v in $schema.Views) {
        $d = if ($v.Default) { ' (기본 보기)' } else { '' }
        Write-AxLog PLAN "보기 $($v.Key).aspx '$($v.Title)'$d  열: $($v.Fields -join ', ')"
        Write-AxLog PLAN "     조건: $($v.Query)"
    }
    return
}

Assert-AxSafeTarget -Config $cfg
if (-not (Get-AxListOrNull -Url $listUrl)) { throw "목록이 없습니다: $listUrl. 02-lists.ps1 을 먼저 실행하세요." }

function Find-AxView {
    param([string]$Key)
    Get-PnPView -List $listUrl -Includes ViewFields, ViewQuery, ServerRelativeUrl, DefaultView, RowLimit, Paged |
        Where-Object { $_.ServerRelativeUrl -match "/$([regex]::Escape($Key))\.aspx$" } | Select-Object -First 1
}

function Format-AxCaml { param([string]$s) ($s -replace '\s+', '' -replace '"', "'") }

foreach ($v in $schema.Views) {
    $view = Find-AxView $v.Key
    if (-not $view) {
        if ($PSCmdlet.ShouldProcess("$listUrl/$($v.Key).aspx", 'Add-PnPView')) {
            Add-PnPView -List $listUrl -Title $v.Key -Fields $v.Fields -Query $v.Query -RowLimit 30 -Paged | Out-Null
            Write-AxLog CHANGE "보기를 만들었습니다: $($v.Key).aspx"
            $view = Find-AxView $v.Key
        }
        if (-not $view) { continue }
    }

    $values = @{}
    if ($view.Title -ne $v.Title) { $values.Title = $v.Title }
    if ((Format-AxCaml $view.ViewQuery) -ne (Format-AxCaml $v.Query)) { $values.ViewQuery = $v.Query }
    if ($v.Default -and -not $view.DefaultView) { $values.DefaultView = $true }
    if ($values.Count -and $PSCmdlet.ShouldProcess("$listUrl/$($v.Key).aspx", 'Set-PnPView ' + ($values.Keys -join ','))) {
        Set-PnPView -List $listUrl -Identity $view.Id -Values $values | Out-Null
        Write-AxLog CHANGE "보기 갱신 $($v.Key): $($values.Keys -join ', ')"
    }

    $haveFields = @($view.ViewFields)
    if (($haveFields -join '|') -ne ($v.Fields -join '|') -and $PSCmdlet.ShouldProcess("$listUrl/$($v.Key).aspx", 'Set-PnPView -Fields')) {
        Set-PnPView -List $listUrl -Identity $view.Id -Fields $v.Fields | Out-Null
        Write-AxLog CHANGE "보기 열 갱신 $($v.Key): $($v.Fields -join ', ')"
    }
    if (-not $values.Count -and ($haveFields -join '|') -eq ($v.Fields -join '|')) { Write-AxLog SKIP "보기가 이미 맞습니다: $($v.Key)" }
}
Write-AxLog OK '보기 준비 완료'
