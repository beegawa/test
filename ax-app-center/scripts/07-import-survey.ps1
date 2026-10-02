<#
.SYNOPSIS
  9단계: 전수 조사 CSV(data/survey-template.csv 양식)를 프로그램 등록부 항목으로 넣는다.
.DESCRIPTION
  - 중복 판단: 프로그램명 + 법인 + 팀 (앞뒤 공백·대소문자 무시). 등록부에 이미 있거나 파일 안에서 반복되면 건너뛴다.
    따라서 같은 파일을 두 번 넣어도 항목이 늘지 않는다. 기존 항목은 고치지 않는다.
  - 선택지 값은 한국어, 영어, 병기 문자열 모두 받는다. 연결 시스템은 ';' 로 여러 개를 적는다.
  - 예/아니오: 예, 아니오, Y, N, Yes, No, TRUE, FALSE, 1, 0. 등급에 쓰이는 세 질문은 비워 둘 수 없다.
  - 오류가 있는 행은 넣지 않고 logs/import-<시각>.csv 에 사유를 남긴다.
  - 넣은 항목에도 흐름 F1이 실행된다 (A등급은 자동 승인, B·C는 승인 요청). docs/admin-guide.md 참고.
.EXAMPLE
  ./07-import-survey.ps1 -CsvPath ../data/survey-2026.csv -WhatIf   # 연결 없이 파일만 검사
  ./07-import-survey.ps1 -CsvPath ../data/survey-2026.csv
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory)][string]$CsvPath,
    [string]$ConfigPath
)

. "$PSScriptRoot/lib/common.ps1"

$ctx = Initialize-AxStep -ConfigPath $ConfigPath -WhatIf ([bool]$WhatIfPreference)
$cfg = $ctx.Config; $schema = $ctx.Schema
$listUrl = $schema.Lists.Registry.Url
Write-AxStep "07 전수 조사 가져오기 ($CsvPath)"

$columns = $schema.SurveyColumns   # CSV 머리글 → 내부 이름 (lib/schema.ps1)
$fieldDefs = @{}; foreach ($f in $schema.Lists.Registry.Fields) { $fieldDefs[$f.Name] = $f }

function ConvertTo-AxBool {
    param([string]$s)
    switch -Regex ($s.Trim()) {
        '^(예|y|yes|true|1|o)$' { return $true }
        '^(아니오|아니요|n|no|false|0|x)$' { return $false }
        default { return $null }
    }
}

function ConvertTo-AxKey { param([string[]]$Parts) (($Parts | ForEach-Object { ([string]$_).Trim().ToLowerInvariant() -replace '\s+', ' ' }) -join '|') }

function Convert-AxRow {
    # CSV 한 행 → @{ Values; Errors }
    param($Row)
    $values = @{}; $errors = [System.Collections.Generic.List[string]]::new()
    foreach ($h in $columns.Keys) {
        $name = $columns[$h]; $f = $fieldDefs[$name]
        $raw = [string]$Row.$h
        $raw = $raw.Trim()
        $required = $f.Required -or $f.FormRequired
        if (-not $raw) {
            if ($required) { $errors.Add("'$h' 이(가) 비어 있음") }
            continue
        }
        switch ($f.Type) {
            'Choice' {
                $label = Get-AxChoiceLabel -Choices $schema.Choices[$f.Choices] -Value $raw
                if ($label) { $values[$name] = $label } else { $errors.Add("'$h' 값 '$raw' 이(가) 선택지에 없음") }
            }
            'MultiChoice' {
                $labels = @()
                foreach ($part in $raw -split '[;\n]' | Where-Object { $_.Trim() }) {
                    $label = Get-AxChoiceLabel -Choices $schema.Choices[$f.Choices] -Value $part
                    if ($label) { $labels += $label } else { $errors.Add("'$h' 값 '$($part.Trim())' 이(가) 선택지에 없음") }
                }
                if ($labels) { $values[$name] = [string[]]($labels | Select-Object -Unique) }
            }
            'Boolean' {
                $b = ConvertTo-AxBool $raw
                if ($null -eq $b) { $errors.Add("'$h' 값 '$raw' 은(는) 예/아니오가 아님") } else { $values[$name] = $b }
            }
            'Number' {
                $n = 0.0
                if ([double]::TryParse(($raw -replace '[,시간h ]', ''), [ref]$n) -and $n -ge 0) { $values[$name] = $n } else { $errors.Add("'$h' 값 '$raw' 은(는) 0 이상의 숫자가 아님") }
            }
            'User' {
                if ($raw -match '^[^@\s]+@[^@\s]+\.[^@\s]+$') { $values[$name] = $raw } else { $errors.Add("'$h' 값 '$raw' 은(는) 메일 주소가 아님") }
            }
            default { $values[$name] = $raw }
        }
    }
    return @{ Values = $values; Errors = $errors }
}

#region CSV 읽기와 검사 (연결 없이)
if (-not (Test-Path $CsvPath)) { throw "CSV 파일이 없습니다: $CsvPath" }
$rows = @(Import-Csv -Path $CsvPath -Encoding utf8)
if ($rows.Count -eq 0) { Write-AxLog WARN 'CSV에 데이터 행이 없습니다.'; return }
$headers = @($rows[0].PSObject.Properties.Name)
$missingHeaders = @($columns.Keys | Where-Object { $_ -notin $headers })
if ($missingHeaders.Count) { throw "CSV 머리글이 양식과 다릅니다. 없는 머리글: $($missingHeaders -join ', ') (data/survey-template.csv 참고)" }

$report = [System.Collections.Generic.List[object]]::new()
$parsed = @()
$line = 1
foreach ($r in $rows) {
    $line++
    $c = Convert-AxRow $r
    $key = ConvertTo-AxKey @($c.Values['Title'], $c.Values['Entity'], $c.Values['Dept'])
    $parsed += [pscustomobject]@{ Line = $line; Key = $key; Values = $c.Values; Errors = $c.Errors }
}
#endregion

if ($ctx.PlanOnly) {
    $seen = @{}
    foreach ($p in $parsed) {
        if (-not $p.Errors.Count -and $seen.ContainsKey($p.Key)) { Write-AxLog SKIP "행 $($p.Line) '$($p.Values['Title'])': 파일 안 중복 (행 $($seen[$p.Key]))"; continue }
        $seen[$p.Key] = $p.Line
        if ($p.Errors.Count) { Write-AxLog WARN "행 $($p.Line) '$($p.Values['Title'])': 오류 $($p.Errors -join '; ')" }
        else {
            $g = Get-AxExpectedGrade -ScopeKey (($schema.Choices.UserScope | Where-Object Label -eq $p.Values['UserScope']).Key) `
                -Internal ([bool]$p.Values['HasInternalData']) -Sensitive ([bool]$p.Values['HasSensitiveData']) -Core ([bool]$p.Values['WritesToCore'])
            Write-AxLog PLAN "행 $($p.Line) '$($p.Values['Title'])' ($($p.Values['Entity'])/$($p.Values['Dept'])) → 추가 예정, 예상 등급 $g (등록부 중복 여부는 연결 후 확인)"
        }
    }
    return
}

Assert-AxSafeTarget -Config $cfg
$existing = @{}
foreach ($it in Get-PnPListItem -List $listUrl -PageSize 500 -Fields 'Title', 'Entity', 'Dept') {
    $existing[(ConvertTo-AxKey @($it['Title'], $it['Entity'], $it['Dept']))] = $it.Id
}

$added = 0; $skipped = 0; $failed = 0
foreach ($p in $parsed) {
    $status = ''; $note = ''
    if ($p.Errors.Count) { $status = '오류'; $note = $p.Errors -join '; '; $failed++ }
    elseif ($existing.ContainsKey($p.Key)) { $status = '건너뜀'; $note = "이미 있음 (ID $($existing[$p.Key]))"; $skipped++ }
    elseif ($PSCmdlet.ShouldProcess("행 $($p.Line) $($p.Values['Title'])", 'Add-PnPListItem')) {
        try {
            $item = Add-PnPListItem -List $listUrl -Values $p.Values
            $existing[$p.Key] = $item.Id
            $status = '추가'; $note = "ID $($item.Id)"; $added++
        }
        catch { $status = '오류'; $note = $_.Exception.Message; $failed++ }
    }
    $lvl = @{ '추가' = 'CHANGE'; '건너뜀' = 'SKIP'; '오류' = 'ERROR' }[$status]
    if ($lvl) { Write-AxLog $lvl "행 $($p.Line) '$($p.Values['Title'])': $status $note" }
    $report.Add([pscustomobject]@{ 행 = $p.Line; 프로그램명 = $p.Values['Title']; 법인 = $p.Values['Entity']; 팀 = $p.Values['Dept']; 결과 = $status; 비고 = $note })
}

$out = Join-Path $script:AxRoot ("logs/import-{0}.csv" -f (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
$report | Export-Csv -Path $out -Encoding utf8BOM -NoTypeInformation
Write-AxLog OK "가져오기 완료: 추가 $added, 건너뜀 $skipped, 오류 $failed. 결과: $out"
if ($failed) { exit 1 }
