<#
.SYNOPSIS
  7단계: 사이트 페이지 2개 (기획서 5.6) — 홈(AppCenterHome.aspx), 등급 기준과 절차(GradeCriteria.aspx).
.DESCRIPTION
  - 기존 Home.aspx 는 지우거나 고치지 않는다. 새 페이지를 만들고 사이트 홈으로 지정한다.
  - 페이지가 이미 있으면 내용은 건드리지 않는다 (웹 파트 중복 방지). 게시와 홈 지정만 맞춘다.
    내용을 다시 만들려면 사람이 페이지를 지운 뒤 다시 실행한다 (스크립트는 삭제하지 않음).
  - 등록/변경 신청 버튼은 자리 표시 링크로 만든다. 양식을 만든 뒤 docs/manual-form.md 대로 바꾼다.
#>
[CmdletBinding(SupportsShouldProcess)]
param([string]$ConfigPath)

. "$PSScriptRoot/lib/common.ps1"

$ctx = Initialize-AxStep -ConfigPath $ConfigPath -WhatIf ([bool]$WhatIfPreference)
$cfg = $ctx.Config; $schema = $ctx.Schema
Write-AxStep '05 사이트 페이지'

$homeName = $schema.Pages.Home
$gradeName = $schema.Pages.Grades
$registerPlaceholder = "$($cfg.SiteUrl)/SitePages/$homeName#TODO-register-form"
$changePlaceholder = "$($cfg.SiteUrl)/SitePages/$homeName#TODO-change-form"
$gradeUrl = "$($cfg.SiteUrl)/SitePages/$gradeName"
$catalogViewUrl = "$($cfg.SiteUrl)/$($schema.Lists.Registry.Url)/Catalog.aspx"

$contact = (@($cfg.people.owners) | ForEach-Object { "<a href=`"mailto:$_`">$_</a>" }) -join ', '
$review = $cfg.review

#region 페이지 내용
$homeIntro = @"
<h2>AX 앱 센터</h2>
<p>법인과 팀이 AI 코딩 도구로 만든 업무 프로그램을 등록하고, 위험 등급에 따라 검토한 뒤, 전 법인이 찾아 쓸 수 있게 모아 둔 곳입니다.</p>
<p>직접 만든 프로그램이 있으면 아래 <strong>프로그램 등록하기</strong>로 등록하세요. 등록된 내용을 바꾸려면 <strong>변경 신청하기</strong>를 쓰세요.</p>
"@

$homeContact = @"
<h3>등급 기준과 절차</h3>
<p><a href="$gradeUrl">등급 기준과 절차 보기</a> · <a href="$catalogViewUrl">카탈로그 전체 보기</a></p>
<h3>문의</h3>
<p>GBI팀: $contact</p>
"@

$gradeText = @"
<h2>위험 등급 기준</h2>
<p>등록 양식의 답변으로 등급이 자동 판정됩니다. 검토자가 확인한 뒤 확정 등급을 정합니다.</p>
<table>
<thead><tr><th>등급</th><th>조건</th><th>처리</th></tr></thead>
<tbody>
<tr><td><strong>A</strong></td><td>본인만 사용하고, 내부 업무 데이터와 민감 데이터를 쓰지 않음</td><td>등록 즉시 승인</td></tr>
<tr><td><strong>B</strong></td><td>C가 아니고, 내부 업무 데이터(오더, 생산 등)를 쓰거나 본인 외에 다른 사람도 사용</td><td>GBI팀 승인 (기한 $($review.slaBusinessDays)영업일)</td></tr>
<tr><td><strong>C</strong></td><td>개인정보·단가·재무 데이터를 쓰거나, ERP·MES에 데이터를 입력하거나, 여러 법인이 함께 사용</td><td>정보보안 담당 → 시스템 담당 → GBI팀 순서로 승인</td></tr>
</tbody>
</table>
<h2>등록부터 승인까지</h2>
<ol>
<li>홈의 <strong>프로그램 등록하기</strong>에서 양식을 제출합니다.</li>
<li>답변에 따라 자동 판정 등급(A/B/C)이 정해집니다.</li>
<li>A등급은 바로 승인되고 등록 완료 메일이 옵니다.</li>
<li>B·C등급은 승인 요청이 담당자에게 갑니다. 결과는 메일로 알려 드리고, 검토 의견은 등록부의 <em>내 프로그램</em> 보기에서 볼 수 있습니다.</li>
<li>승인된 프로그램은 카탈로그에 나오고, $($review.recheckMonths)개월마다 정기 점검 요청을 받습니다.</li>
<li>내용이 바뀌거나 사용을 멈출 때는 <strong>변경 신청하기</strong>로 알립니다.</li>
</ol>
<h2>임시 보안 수칙</h2>
<ul>
<li>계정, 비밀번호, API 키를 코드나 파일에 직접 적지 않습니다.</li>
<li>개인정보·단가·재무 데이터를 외부 AI 도구에 붙여 넣지 않습니다.</li>
<li>ERP·MES에 데이터를 입력하는 프로그램은 C등급 승인 전에 운영 시스템에 연결하지 않습니다.</li>
<li>승인 전에는 회사 데이터를 외부 클라우드에 올리지 않습니다.</li>
<li>코드와 파일은 회사 저장소에 두고, 위치를 등록부의 <em>코드·파일 위치</em>에 적습니다.</li>
<li>만든 사람이 이동하거나 퇴사하면 변경 신청으로 담당자를 바꿉니다.</li>
</ul>
<p>문의: $contact</p>
"@
#endregion

if ($ctx.PlanOnly) {
    Write-AxLog PLAN "페이지 $gradeName : 등급 표, 등록~승인 순서, 임시 보안 수칙"
    Write-AxLog PLAN "페이지 $homeName : 소개, 버튼 2개(자리 표시 링크), 등록부 '카탈로그' 목록 웹 파트, 문의처"
    Write-AxLog PLAN "   버튼 '프로그램 등록하기' → $registerPlaceholder"
    Write-AxLog PLAN "   버튼 '변경 신청하기'   → $changePlaceholder"
    Write-AxLog PLAN "사이트 홈 페이지를 SitePages/$homeName 로 지정"
    return
}

Assert-AxSafeTarget -Config $cfg

function Get-AxPageOrNull { param([string]$Name) Get-PnPPage -Identity $Name -ErrorAction SilentlyContinue }

function Add-AxButton {
    param([string]$Page, [string]$Label, [string]$Url, [int]$Section, [int]$Column)
    # Button 웹 파트 속성 이름은 공개 문서가 없어 label/title 을 함께 넣는다. 화면 확인 결과는 verification-log 에 남긴다.
    $props = @{ label = $Label; title = $Label; linkUrl = $Url; alignment = 'Center' } | ConvertTo-Json -Compress
    try {
        Add-PnPPageWebPart -Page $Page -DefaultWebPartType Button -WebPartProperties $props -Section $Section -Column $Column | Out-Null
    }
    catch {
        Write-AxLog WARN "Button 웹 파트 추가 실패, 텍스트 링크로 대신합니다: $($_.Exception.Message)"
        Add-PnPPageTextPart -Page $Page -Section $Section -Column $Column -Text "<p style=`"text-align:center`"><a href=`"$Url`"><strong>$Label</strong></a></p>" | Out-Null
    }
}

#region 등급 기준 페이지
if (Get-AxPageOrNull $gradeName) {
    Write-AxLog SKIP "페이지가 이미 있습니다: $gradeName (내용은 건드리지 않음)"
}
elseif ($PSCmdlet.ShouldProcess($gradeName, 'Add-PnPPage')) {
    Add-PnPPage -Name ($gradeName -replace '\.aspx$') -LayoutType Article | Out-Null
    Add-PnPPageSection -Page $gradeName -SectionTemplate OneColumn | Out-Null
    Add-PnPPageTextPart -Page $gradeName -Section 1 -Column 1 -Text $gradeText | Out-Null
    Set-PnPPage -Identity $gradeName -Title '등급 기준과 절차' -Publish | Out-Null
    Write-AxLog CHANGE "페이지를 만들었습니다: $gradeName"
}
#endregion

#region 홈 페이지
if (Get-AxPageOrNull $homeName) {
    Write-AxLog SKIP "페이지가 이미 있습니다: $homeName (내용은 건드리지 않음)"
}
elseif ($PSCmdlet.ShouldProcess($homeName, 'Add-PnPPage')) {
    $list = Get-PnPList -Identity $schema.Lists.Registry.Url
    $catalog = Get-PnPView -List $schema.Lists.Registry.Url | Where-Object { $_.ServerRelativeUrl -match '/Catalog\.aspx$' } | Select-Object -First 1
    if (-not $catalog) { throw '카탈로그 보기가 없습니다. 03-views.ps1 을 먼저 실행하세요.' }

    Add-PnPPage -Name ($homeName -replace '\.aspx$') -LayoutType Article | Out-Null
    Add-PnPPageSection -Page $homeName -SectionTemplate OneColumn -Order 1 | Out-Null
    Add-PnPPageSection -Page $homeName -SectionTemplate TwoColumn -Order 2 | Out-Null
    Add-PnPPageSection -Page $homeName -SectionTemplate OneColumn -Order 3 | Out-Null
    Add-PnPPageSection -Page $homeName -SectionTemplate OneColumn -Order 4 | Out-Null

    Add-PnPPageTextPart -Page $homeName -Section 1 -Column 1 -Text $homeIntro | Out-Null
    Add-AxButton -Page $homeName -Label '프로그램 등록하기' -Url $registerPlaceholder -Section 2 -Column 1
    Add-AxButton -Page $homeName -Label '변경 신청하기' -Url $changePlaceholder -Section 2 -Column 2

    $listProps = @{
        isDocumentLibrary   = $false
        selectedListId      = $list.Id.ToString()
        selectedListUrl     = "$($cfg.SiteServerRelativeUrl)/$($schema.Lists.Registry.Url)"
        webRelativeListUrl  = "/$($schema.Lists.Registry.Url)"
        listTitle           = $list.Title
        selectedViewId      = $catalog.Id.ToString()
        webpartHeightKey    = 4
        hideCommandBar      = $false
    } | ConvertTo-Json -Compress
    try {
        Add-PnPPageWebPart -Page $homeName -DefaultWebPartType List -WebPartProperties $listProps -Section 3 -Column 1 | Out-Null
    }
    catch {
        Write-AxLog WARN "목록 웹 파트 추가 실패, 보기 링크로 대신합니다 (8장 대안): $($_.Exception.Message)"
        Add-PnPPageTextPart -Page $homeName -Section 3 -Column 1 -Text "<h3>카탈로그</h3><p><a href=`"$catalogViewUrl`">승인된 프로그램 전체 보기</a></p>" | Out-Null
    }
    Add-PnPPageTextPart -Page $homeName -Section 4 -Column 1 -Text $homeContact | Out-Null
    Set-PnPPage -Identity $homeName -Title $cfg.site.title -Publish | Out-Null
    Write-AxLog CHANGE "페이지를 만들었습니다: $homeName"
}
#endregion

#region 홈 지정
$currentHome = Get-PnPHomePage
if ($currentHome -ne "SitePages/$homeName" -and $PSCmdlet.ShouldProcess('사이트', "홈 페이지를 SitePages/$homeName 로")) {
    Set-PnPHomePage -RootFolderRelativeUrl "SitePages/$homeName"
    Write-AxLog CHANGE "홈 페이지 지정: $currentHome → SitePages/$homeName"
}
else { Write-AxLog SKIP "홈 페이지가 이미 SitePages/$homeName 입니다" }
#endregion

Write-AxLog WARN "버튼 링크는 자리 표시입니다. 양식을 만든 뒤 docs/manual-form.md 4·6단계대로 바꾸세요."
Write-AxLog OK '페이지 준비 완료'
