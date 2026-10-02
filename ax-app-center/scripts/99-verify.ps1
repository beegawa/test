<#
.SYNOPSIS
  완료 기준 자동 점검 (기획서 6장). 실패가 하나라도 있으면 종료 코드 1.
.DESCRIPTION
  오프라인 점검 (항상 실행, 연결 없음)
    - 설정 값, 열 XML, 보기 CAML 이 올바른 XML 인지
    - 등급 규칙과 '생성한 수식 문자열'을 해석기로 돌려 7.1 표의 기대 등급과 같은지
    - 전수 조사 CSV 양식의 머리글이 가져오기 스크립트와 같은지
  온라인 점검 (-Offline 이 아니면)
    site    사이트, 언어, 템플릿
    lists   목록 3개, 버전·첨부 설정, 모든 열의 내부 이름·형식·필수·표시 이름·선택지
    grade   [TEST] 항목의 자동 판정 등급이 기대 등급과 같은지 (06-seed-test-data.ps1 먼저)
    views   보기 6개, 기본 보기 = 카탈로그
    perms   상속 끊김, 그룹별 역할, 방문자 그룹에 '외부 사용자를 제외한 모든 사용자'
    pages   페이지 2개, 홈 지정, 목록 웹 파트, 버튼 2개
.EXAMPLE
  ./99-verify.ps1 -Offline -ConfigPath ../config/config.sample.json
  ./99-verify.ps1 -Stage lists, grade
#>
[CmdletBinding()]
param(
    [string]$ConfigPath,
    [switch]$Offline,
    [ValidateSet('site', 'lists', 'grade', 'views', 'perms', 'pages')]
    [string[]]$Stage = @('site', 'lists', 'grade', 'views', 'perms', 'pages')
)

. "$PSScriptRoot/lib/common.ps1"
. "$PSScriptRoot/lib/formula.ps1"

$results = [System.Collections.Generic.List[object]]::new()
function Add-Result {
    param([string]$Area, [ValidateSet('PASS', 'FAIL', 'WARN', 'SKIP')][string]$State, [string]$Check, [string]$Detail = '')
    $results.Add([pscustomobject]@{ Area = $Area; State = $State; Check = $Check; Detail = $Detail })
}
function Test-That {
    param([string]$Area, [string]$Check, [bool]$Ok, [string]$Detail = '')
    Add-Result -Area $Area -State $(if ($Ok) { 'PASS' } else { 'FAIL' }) -Check $Check -Detail $Detail
}

$cfg = Read-AxConfig -ConfigPath $ConfigPath -ForConnect:(-not $Offline)
$schema = Get-AxSchema -Config $cfg
Write-AxStep "99 점검 ($($cfg.SiteUrl), $(if ($Offline) { '오프라인' } else { '온라인' }))"

#region 오프라인
Test-That config "environment=$($cfg.environment) → 사이트 URL" ($cfg.environment -eq 'prod' -or $cfg.SiteUrl -match '-test$') $cfg.SiteUrl
if ($cfg.MissingValues.Count) { Add-Result config WARN '사람이 정할 값' ($cfg.MissingValues -join ', ') }
else { Add-Result config PASS '사람이 정할 값' '모두 채워짐' }

foreach ($l in $schema.Lists.Values) {
    $names = @($l.Fields | ForEach-Object { $_.Name })
    Test-That schema "$($l.Url) 내부 이름 중복 없음" ($names.Count -eq @($names | Select-Object -Unique).Count)
    foreach ($f in $l.Fields) {
        $formula = if ($f.Type -eq 'Calculated') { $schema.FormulaTemplate -f '[HasSensitiveData]', '[WritesToCore]', '[UserScope]', '[HasInternalData]' } else { $null }
        $ff = $f.Clone(); if ($formula) { $ff.Refs = $schema.FormulaRefs }
        try { $null = [xml](Get-AxFieldXml -Field $ff -Choices $schema.Choices -Formula $formula); $ok = $true; $msg = '' } catch { $ok = $false; $msg = $_.Exception.Message }
        if (-not $ok) { Test-That schema "$($l.Url)/$($f.Name) 열 XML" $false $msg }
    }
}
Add-Result schema PASS '열 XML 생성' "$(@($schema.Lists.Values | ForEach-Object { $_.Fields }).Count)개 검사"
foreach ($v in $schema.Views) {
    try { $null = [xml]("<Query>$($v.Query)</Query>"); Test-That schema "보기 $($v.Key) CAML" $true }
    catch { Test-That schema "보기 $($v.Key) CAML" $false $_.Exception.Message }
}
Test-That schema '보기 6개, 기본 보기 카탈로그' ($schema.Views.Count -eq 6 -and @($schema.Views | Where-Object { $_.Default }).Count -eq 1 -and ($schema.Views | Where-Object { $_.Default }).Key -eq 'Catalog')

# 등급: 규칙 함수와 실제 수식 문자열 모두 7.1 표와 비교
$formulaText = $schema.FormulaTemplate -f '[HasSensitiveData]', '[WritesToCore]', '[UserScope]', '[HasInternalData]'
foreach ($c in $schema.TestCases) {
    $byRule = Get-AxExpectedGrade -ScopeKey $c.Scope -Internal $c.Internal -Sensitive $c.Sensitive -Core $c.Core
    $row = @{
        HasSensitiveData = [bool]$c.Sensitive; WritesToCore = [bool]$c.Core; HasInternalData = [bool]$c.Internal
        UserScope = (Get-AxChoiceLabel -Choices $schema.Choices.UserScope -Value $c.Scope)
    }
    try { $byFormula = Invoke-AxFormula -Formula $formulaText -Row $row } catch { $byFormula = "오류: $($_.Exception.Message)" }
    Test-That grade-offline "$($c.Title)" ($byRule -eq $c.Expected -and $byFormula -eq $c.Expected) "기대 $($c.Expected) / 규칙 $byRule / 수식 $byFormula"
}

$tpl = Join-Path $script:AxRoot 'data/survey-template.csv'
$tplHeaders = @((Get-Content -Path $tpl -Encoding utf8 -TotalCount 1).Trim([char]0xFEFF) -split ',' | ForEach-Object { $_.Trim('"', ' ') })
Test-That survey 'CSV 양식 머리글 = 가져오기 열' (($tplHeaders -join '|') -eq (@($schema.SurveyColumns.Keys) -join '|')) ($tplHeaders -join ', ')
#endregion

#region 온라인
if (-not $Offline) {
    Assert-AxSafeTarget -Config $cfg
    if (-not (Test-AxConnected -Url $cfg.SiteUrl)) { Connect-AxSite -Config $cfg -Url $cfg.SiteUrl }

    if ('site' -in $Stage) {
        $web = Get-PnPWeb -Includes Language, WebTemplate, Title
        Test-That site '사이트 열림' ($null -ne $web) $cfg.SiteUrl
        Test-That site '언어' ($web.Language -eq [uint32]$cfg.site.lcid) "$($web.Language)"
        Test-That site '커뮤니케이션 사이트' ($web.WebTemplate -eq 'SITEPAGEPUBLISHING') $web.WebTemplate
        Test-That site '제목' ($web.Title -eq $cfg.site.title) $web.Title
    }

    if ('lists' -in $Stage) {
        foreach ($l in $schema.Lists.Values) {
            $list = Get-PnPList -Identity $l.Url -Includes EnableVersioning, MajorVersionLimit, EnableAttachments -ErrorAction SilentlyContinue
            Test-That lists "$($l.Url) 있음" ($null -ne $list) $l.Title
            if (-not $list) { continue }
            Test-That lists "$($l.Url) 표시 이름" ($list.Title -eq $l.Title) $list.Title
            if ($l.Versioning) { Test-That lists "$($l.Url) 버전 관리 $($l.MajorVersions)개" ($list.EnableVersioning -and $list.MajorVersionLimit -eq $l.MajorVersions) "$($list.EnableVersioning)/$($list.MajorVersionLimit)" }
            if ($null -ne $l.Attachments) { Test-That lists "$($l.Url) 첨부 파일 끔" ($list.EnableAttachments -eq $l.Attachments) "$($list.EnableAttachments)" }

            $fields = @{}; foreach ($f in Get-PnPField -List $l.Url) { $fields[$f.InternalName] = $f }
            foreach ($f in $l.Fields) {
                $id = "$($l.Url)/$($f.Name)"
                if (-not $fields.ContainsKey($f.Name)) { Test-That lists "$id 있음" $false; continue }
                $a = $fields[$f.Name]
                if ($f.Type -eq 'Calculated' -and $a.TypeAsString -eq $f.FallbackType) {
                    Add-Result lists WARN "$id 형식" "계산 열 대안($($a.TypeAsString)) 사용 중 — F1이 등급을 채워야 함"
                }
                else { Test-That lists "$id 형식" ($a.TypeAsString -eq $f.Type) "$($a.TypeAsString)" }
                Test-That lists "$id 필수" ([bool]$a.Required -eq [bool]$f.Required) "$($a.Required)"
                Test-That lists "$id 표시 이름" ($a.Title -eq $f.Display) $a.Title
                if ($f.Choices -and $a.TypeAsString -in 'Choice', 'MultiChoice') {
                    $have = @(([xml]$a.SchemaXml).Field.CHOICES.CHOICE | ForEach-Object { if ($_ -is [string]) { $_ } else { $_.InnerText } })
                    $miss = @($schema.Choices[$f.Choices] | ForEach-Object { $_.Label } | Where-Object { $_ -notin $have })
                    Test-That lists "$id 선택지" ($miss.Count -eq 0) $(if ($miss) { '없음: ' + ($miss -join ', ') } else { '' })
                }
            }
        }
    }

    if ('grade' -in $Stage) {
        $items = @(Get-PnPListItem -List $schema.Lists.Registry.Url -PageSize 500 -Fields 'Title', 'AutoGrade' |
                Where-Object { ([string]$_['Title']).StartsWith($schema.TestPrefix) })
        $gradeField = Get-PnPField -List $schema.Lists.Registry.Url | Where-Object { $_.InternalName -eq 'AutoGrade' }
        $gradeIsFallback = ($gradeField -and $gradeField.TypeAsString -ne 'Calculated')
        if (-not $items) { Add-Result grade SKIP '테스트 항목' '없음. 06-seed-test-data.ps1 을 먼저 실행하세요 (test 환경).' }
        foreach ($c in $schema.TestCases) {
            $it = $items | Where-Object { $_['Title'] -eq ($schema.TestPrefix + $c.Title) } | Select-Object -First 1
            if (-not $it) { continue }
            $g = [string]$it['AutoGrade']
            if (-not $g -and $gradeIsFallback) { Add-Result grade WARN "$($c.Title) (ID $($it.Id))" "기대 $($c.Expected) / 비어 있음 — 계산 열 대안 사용 중, 흐름 F1이 채운 뒤 다시 점검"; continue }
            Test-That grade "$($c.Title) (ID $($it.Id))" ($g -eq $c.Expected) "기대 $($c.Expected) / 실제 '$g'"
        }
    }

    if ('views' -in $Stage) {
        $views = @(Get-PnPView -List $schema.Lists.Registry.Url -Includes ServerRelativeUrl, DefaultView, ViewFields)
        foreach ($v in $schema.Views) {
            $view = $views | Where-Object { $_.ServerRelativeUrl -match "/$($v.Key)\.aspx$" } | Select-Object -First 1
            Test-That views "보기 $($v.Key)" ($null -ne $view -and $view.Title -eq $v.Title) $(if ($view) { $view.Title } else { '없음' })
            if ($view) { Test-That views "보기 $($v.Key) 열" ((@($view.ViewFields) -join '|') -eq ($v.Fields -join '|')) (@($view.ViewFields) -join ', ') }
        }
        $def = $views | Where-Object DefaultView | Select-Object -First 1
        Test-That views '기본 보기 = 카탈로그' ($def -and $def.ServerRelativeUrl -match '/Catalog\.aspx$') $(if ($def) { $def.Title } else { '' })
    }

    if ('perms' -in $Stage) {
        $owners = Get-PnPGroup -AssociatedOwnerGroup
        $visitors = Get-PnPGroup -AssociatedVisitorGroup
        $reviewers = Get-PnPGroup -Identity $schema.Groups.Reviewers -ErrorAction SilentlyContinue
        $members = $null; try { $members = Get-PnPGroup -AssociatedMemberGroup } catch { }
        Test-That perms "그룹 '$($schema.Groups.Reviewers)'" ($null -ne $reviewers)
        $tenantId = Get-PnPTenantId
        $vm = @(Get-PnPGroupMember -Group $visitors.Title | ForEach-Object { $_.LoginName })
        Test-That perms '방문자 그룹 = 외부 사용자를 제외한 모든 사용자' ($vm -contains "c:0-.f|rolemanager|spo-grid-all-users/$tenantId") $visitors.Title
        if ($reviewers) {
            $rm = @(Get-PnPGroupMember -Group $reviewers.Title | ForEach-Object { ([string]$_.Email).ToLowerInvariant() })
            $missing = @(Get-AxAllPeople -Config $cfg | Where-Object { $_ -notin $rm })
            Test-That perms '검토자 그룹 구성원' ($missing.Count -eq 0) $(if ($missing) { '없음: ' + ($missing -join ', ') } else { '' })
        }
        $om = @(Get-PnPGroupMember -Group $owners.Title | ForEach-Object { ([string]$_.Email).ToLowerInvariant() })
        $missingOwners = @($cfg.people.owners | ForEach-Object { $_.ToLowerInvariant() } | Where-Object { $_ -notin $om })
        Test-That perms '소유자 그룹 구성원' ($missingOwners.Count -eq 0) $(if ($missingOwners) { '없음: ' + ($missingOwners -join ', ') } else { '' })

        $visitorKind = if ($cfg.permissions.visitorsCanSubmit) { 'Contributor' } else { 'Reader' }
        function Get-Kinds($url, $g) { try { @(Get-PnPListPermissions -Identity $url -PrincipalId $g.Id | ForEach-Object { [string]$_.RoleTypeKind } | Where-Object { $_ -notin 'Guest', 'None' }) } catch { @() } }
        foreach ($l in $schema.Lists.Values) {
            $list = Get-PnPList -Identity $l.Url -Includes HasUniqueRoleAssignments -ErrorAction SilentlyContinue
            if (-not $list) { Test-That perms "$($l.Url) 있음" $false; continue }
            Test-That perms "$($l.Url) 상속 끊김" ([bool]$list.HasUniqueRoleAssignments)
            $vk = if ($l.Key -eq 'Docs') { 'Reader' } else { $visitorKind }
            $o = @(Get-Kinds $l.Url $owners); Test-That perms "$($l.Url) 소유자 = 모든 권한" (($o -join ',') -eq 'Administrator') ($o -join ',')
            if ($reviewers) { $r = @(Get-Kinds $l.Url $reviewers); Test-That perms "$($l.Url) 검토자 = 편집" (($r -join ',') -eq 'Editor') ($r -join ',') }
            $v = @(Get-Kinds $l.Url $visitors); Test-That perms "$($l.Url) 방문자 = $vk" (($v -join ',') -eq $vk) ($v -join ',')
            if ($members) { $m = @(Get-Kinds $l.Url $members); Test-That perms "$($l.Url) 구성원 그룹 권한 없음" ($m.Count -eq 0) ($m -join ',') }
        }
    }

    if ('pages' -in $Stage) {
        foreach ($p in $schema.Pages.Values) {
            $page = Get-PnPPage -Identity $p -ErrorAction SilentlyContinue
            Test-That pages "페이지 $p" ($null -ne $page)
        }
        $homePath = Get-PnPHomePage
        Test-That pages '사이트 홈' ($homePath -eq "SitePages/$($schema.Pages.Home)") $homePath
        $comps = @(Get-PnPPageComponent -Page $schema.Pages.Home -ErrorAction SilentlyContinue)
        $json = ($comps | ForEach-Object { $_ | ConvertTo-Json -Depth 4 -WarningAction SilentlyContinue }) -join "`n"
        $listPart = $comps | Where-Object { $_.PSObject.Properties['WebPartId'] -and $_.WebPartId -eq 'f92bf067-bc19-489e-a556-7fe95f508720' }
        if ($listPart) { Test-That pages '홈: 카탈로그 목록 웹 파트' $true }
        else { Add-Result pages WARN '홈: 카탈로그 목록 웹 파트' '없음 — 대안(보기 링크) 또는 수동 추가 필요. 화면에서 확인하세요.' }
        foreach ($label in '프로그램 등록하기', '변경 신청하기') {
            Test-That pages "홈: '$label' 버튼" ($json -match [regex]::Escape($label))
        }
        if ($json -match 'TODO-(register|change)-form') { Add-Result pages WARN '홈: 버튼 링크' '아직 자리 표시 링크입니다 (docs/manual-form.md)' }
    }
}
#endregion

#region 결과
Write-Host ''
$results | Format-Table -AutoSize -Wrap Area, State, Check, Detail | Out-String -Width 200 | Write-Host
$fail = @($results | Where-Object State -eq 'FAIL').Count
$warn = @($results | Where-Object State -eq 'WARN').Count
$pass = @($results | Where-Object State -eq 'PASS').Count
$level = if ($fail) { 'ERROR' } elseif ($warn) { 'WARN' } else { 'OK' }
Write-AxLog $level "점검 결과: 통과 $pass, 실패 $fail, 경고 $warn"
if ($fail) { exit 1 }
#endregion
