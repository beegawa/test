<#
.SYNOPSIS
  2·3·4단계: 목록 2개(프로그램 등록부, 변경 신청)와 라이브러리 1개(프로그램 자료), 열, 등급 자동 판정 수식 (기획서 5.3~5.5).
.DESCRIPTION
  순서
   1) 목록이 없으면 만들고 설정(버전 50개, 첨부 끔)을 맞춘다.
   2) 없는 열을 영문 내부 이름으로 만든다 (처음에는 표시 이름 = 내부 이름).
   3) 계산 열 AutoGrade 를 만든다. 수식은 참조 열의 현재 표시 이름으로 채운다.
      실패하면 AutoGrade 를 선택 열(A/B/C)로 만들고 흐름 F1에서 채우게 한다 (기획서 5.3 대안).
   4) 표시 이름, 필수 여부, 기본값, 설명, 선택지를 맞춘다.
  삭제는 하지 않는다. 형식이 다른 기존 열, 설계에 없는 선택지는 경고만 남긴다.
#>
[CmdletBinding(SupportsShouldProcess)]
param([string]$ConfigPath)

. "$PSScriptRoot/lib/common.ps1"

$ctx = Initialize-AxStep -ConfigPath $ConfigPath -WhatIf ([bool]$WhatIfPreference)
$cfg = $ctx.Config; $schema = $ctx.Schema
Write-AxStep '02 목록과 열'

if ($ctx.PlanOnly) {
    foreach ($l in $schema.Lists.Values) {
        Write-AxLog PLAN ("목록 확인/생성: $($l.Url)  '$($l.Title)'  ($($l.Template))" + $(if ($l.Versioning) { "  버전 $($l.MajorVersions)개" } else { '' }))
        foreach ($f in $l.Fields) {
            $req = if ($f.Required -or $f.FormRequired) { '필수' } else { '' }
            $ch = if ($f.Choices) { ' [' + (($schema.Choices[$f.Choices] | ForEach-Object { $_.Label }) -join ', ') + ']' } else { '' }
            Write-AxLog PLAN ("   열 {0,-18} {1,-12} {2,-4} '{3}'{4}" -f $f.Name, $f.Type, $req, $f.Display, $ch)
        }
    }
    Write-AxLog PLAN ('   등급 수식: ' + ($schema.FormulaTemplate -f '[HasSensitiveData]', '[WritesToCore]', '[UserScope]', '[HasInternalData]'))
    return
}

$problems = [System.Collections.Generic.List[string]]::new()

function Get-AxChoicesFromSchemaXml {
    param([string]$SchemaXml)
    $x = [xml]$SchemaXml
    return @($x.Field.CHOICES.CHOICE | ForEach-Object { if ($_ -is [string]) { $_ } else { $_.InnerText } })
}

function Get-AxFieldMap {
    param([string]$ListUrl)
    $map = @{}
    foreach ($f in Get-PnPField -List $ListUrl) { $map[$f.InternalName] = $f }
    return $map
}

function Set-AxFieldValues {
    param([string]$ListUrl, [string]$Name, [hashtable]$Values, [string]$What)
    if ($PSCmdlet.ShouldProcess("$ListUrl/$Name", $What)) {
        Set-PnPField -List $ListUrl -Identity $Name -Values $Values | Out-Null
        Write-AxLog CHANGE "$ListUrl / $Name : $What"
    }
}

foreach ($def in $schema.Lists.Values) {
    Assert-AxSafeTarget -Config $cfg

    #region 1) 목록
    $list = Get-AxListOrNull -Url $def.Url
    if (-not $list) {
        if ($PSCmdlet.ShouldProcess($def.Url, "New-PnPList '$($def.Title)'")) {
            $list = New-PnPList -Title $def.Title -Template $def.Template -Url $def.Url
            Write-AxLog CHANGE "목록을 만들었습니다: $($def.Url) '$($def.Title)'"
            $list = Get-AxListOrNull -Url $def.Url
        }
    }
    else { Write-AxLog SKIP "목록이 이미 있습니다: $($def.Url)" }
    if (-not $list) { continue }

    $list = Get-PnPList -Identity $def.Url -Includes EnableVersioning, MajorVersionLimit, EnableAttachments, EnableFolderCreation, BaseType
    $set = @{}
    if ($list.Title -ne $def.Title) { $set.Title = $def.Title }
    if ($def.Versioning) {
        if (-not $list.EnableVersioning) { $set.EnableVersioning = $true }
        if ($list.MajorVersionLimit -ne $def.MajorVersions) { $set.MajorVersions = [uint32]$def.MajorVersions; $set.EnableVersioning = $true }
    }
    if ($null -ne $def.Attachments -and [string]$list.BaseType -eq 'GenericList' -and $list.EnableAttachments -ne $def.Attachments) { $set.EnableAttachments = $def.Attachments }
    if ($list.EnableFolderCreation) { $set.EnableFolderCreation = $false }
    if ($set.Count -and $PSCmdlet.ShouldProcess($def.Url, 'Set-PnPList ' + ($set.Keys -join ','))) {
        Set-PnPList -Identity $def.Url @set | Out-Null
        Write-AxLog CHANGE ("목록 설정: $($def.Url) " + (($set.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join ', '))
    }
    #endregion

    #region 2) 열 만들기 (계산 열 제외)
    $fields = Get-AxFieldMap $def.Url
    foreach ($f in $def.Fields | Where-Object { $_.Type -ne 'Calculated' -and -not $_.Builtin }) {
        if ($fields.ContainsKey($f.Name)) {
            $actual = $fields[$f.Name].TypeAsString
            $expected = if ($f.Type -eq 'User') { 'User' } else { $f.Type }
            if ($actual -ne $expected) {
                $problems.Add("$($def.Url)/$($f.Name): 형식이 $actual 입니다 (설계 $expected). 자동으로 바꾸지 않습니다.")
            }
            continue
        }
        $xml = Get-AxFieldXml -Field $f -Choices $schema.Choices
        if ($PSCmdlet.ShouldProcess("$($def.Url)/$($f.Name)", 'Add-PnPFieldFromXml')) {
            Add-PnPFieldFromXml -List $def.Url -FieldXml $xml | Out-Null
            Write-AxLog CHANGE "열을 만들었습니다: $($def.Url) / $($f.Name) ($($f.Type))"
        }
    }
    #endregion

    #region 3) 계산 열 (등록부의 AutoGrade)
    foreach ($f in $def.Fields | Where-Object { $_.Type -eq 'Calculated' }) {
        $fields = Get-AxFieldMap $def.Url
        $refTitles = foreach ($r in $schema.FormulaRefs) {
            if (-not $fields.ContainsKey($r)) { throw "계산 열이 참조할 열이 없습니다: $r" }
            '[' + $fields[$r].Title + ']'
        }
        $formula = $schema.FormulaTemplate -f $refTitles

        if ($fields.ContainsKey($f.Name)) {
            $existing = $fields[$f.Name]
            if ($existing.TypeAsString -eq 'Calculated') {
                $current = ([xml]$existing.SchemaXml).Field.Formula
                if (($current -replace '\s', '') -ne ($formula -replace '\s', '')) {
                    Set-AxFieldValues -ListUrl $def.Url -Name $f.Name -Values @{ Formula = $formula } -What '수식 갱신'
                }
                else { Write-AxLog SKIP "$($def.Url) / $($f.Name): 수식이 같습니다" }
            }
            else {
                Write-AxLog WARN "$($def.Url) / $($f.Name) 는 $($existing.TypeAsString) 열입니다 (계산 열 대안 사용 중). 등급은 흐름 F1이 채웁니다."
            }
            continue
        }

        $calc = $f.Clone(); $calc.Refs = $schema.FormulaRefs
        $xml = Get-AxFieldXml -Field $calc -Choices $schema.Choices -Formula $formula
        if ($PSCmdlet.ShouldProcess("$($def.Url)/$($f.Name)", 'Add-PnPFieldFromXml (Calculated)')) {
            try {
                Add-PnPFieldFromXml -List $def.Url -FieldXml $xml | Out-Null
                Write-AxLog CHANGE "계산 열을 만들었습니다: $($f.Name)  $formula"
            }
            catch {
                Write-AxLog WARN "계산 열 생성 실패: $($_.Exception.Message)"
                Write-AxLog WARN "대안: $($f.Name) 을 선택 열(A/B/C)로 만들고 흐름 F1에서 같은 규칙으로 채웁니다. docs/verification-log.md 에 기록하세요."
                $xml = Get-AxFieldXml -Field $f -Choices $schema.Choices -TypeOverride $f.FallbackType
                Add-PnPFieldFromXml -List $def.Url -FieldXml $xml | Out-Null
                Write-AxLog CHANGE "대안 열을 만들었습니다: $($f.Name) (Choice)"
            }
        }
    }
    #endregion

    #region 4) 표시 이름, 필수, 기본값, 설명, 선택지
    $fields = Get-AxFieldMap $def.Url
    foreach ($f in $def.Fields) {
        if (-not $fields.ContainsKey($f.Name)) { continue }
        $cur = $fields[$f.Name]
        $values = @{}
        if ($cur.Title -ne $f.Display) { $values.Title = $f.Display }
        if ($cur.TypeAsString -ne 'Calculated' -and [bool]$cur.Required -ne [bool]$f.Required) { $values.Required = [bool]$f.Required }
        $desc = if ($f.Description) { $f.Description } else { '' }
        if ([string]$cur.Description -ne $desc) { $values.Description = $desc }
        if ($null -ne $f.Default -and $cur.TypeAsString -ne 'Calculated' -and [string]$cur.DefaultValue -ne [string]$f.Default) { $values.DefaultValue = [string]$f.Default }

        if ($f.Choices -and $cur.TypeAsString -in 'Choice', 'MultiChoice') {
            $want = @($schema.Choices[$f.Choices] | ForEach-Object { $_.Label })
            $have = Get-AxChoicesFromSchemaXml $cur.SchemaXml
            $missing = @($want | Where-Object { $_ -notin $have })
            $extra = @($have | Where-Object { $_ -notin $want })
            if ($missing.Count) { $values.Choices = [string[]]@($have + $missing) }
            if ($extra.Count) { Write-AxLog WARN "$($def.Url) / $($f.Name): 설계에 없는 선택지가 있습니다 (지우지 않음): $($extra -join ', ')" }
        }
        if ($values.Count) {
            Set-AxFieldValues -ListUrl $def.Url -Name $f.Name -Values $values -What ('갱신 ' + ($values.Keys -join ','))
        }
    }
    #endregion
}

if ($problems.Count) {
    $problems | ForEach-Object { Write-AxLog ERROR $_ }
    throw "열 형식 불일치 $($problems.Count)건. 사람이 확인해야 합니다 (자동 삭제·재생성 안 함)."
}
Write-AxLog OK '목록과 열 준비 완료'
