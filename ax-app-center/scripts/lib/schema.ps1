# AX 앱 센터 설계 정의 (기획서 5장). 연결 없이 계산되는 "원하는 상태".
# 02~05, 06, 07, 99 스크립트가 모두 여기서 열·선택지·보기 정의를 가져온다.
# 표시 문자열은 config.labels.bilingual 이 true 면 '한국어 / English' 로 만든다.

function Get-AxLabel {
    param([Parameter(Mandatory)][string]$Ko, [string]$En, [bool]$Bilingual)
    if ($Bilingual -and $En -and $En -ne $Ko) { return "$Ko / $En" }
    return $Ko
}

function New-AxChoiceSet {
    # @(@('본인만','Only me'), ...) → 선택지 객체 목록. Key 는 한국어(내부 비교용), Label 은 실제 저장 문자열.
    param([Parameter(Mandatory)][object[]]$Pairs, [bool]$Bilingual)
    foreach ($p in $Pairs) {
        $ko = $p[0]; $en = if ($p.Count -gt 1) { $p[1] } else { $null }
        [pscustomobject]@{ Key = $ko; En = $en; Label = (Get-AxLabel -Ko $ko -En $en -Bilingual $Bilingual) }
    }
}

function Get-AxChoiceLabel {
    # 선택지 집합에서 한국어 키(또는 영문, 또는 전체 라벨)로 저장 문자열을 찾는다. 없으면 $null.
    param([Parameter(Mandatory)][object[]]$Choices, [Parameter(Mandatory)][string]$Value)
    $v = $Value.Trim()
    foreach ($c in $Choices) {
        if ($v -eq $c.Key -or $v -eq $c.Label -or ($c.En -and $v -ieq $c.En)) { return $c.Label }
    }
    return $null
}

function Get-AxSchema {
    param([Parameter(Mandatory)][hashtable]$Config)

    $bi = [bool]$Config.labels.bilingual
    function L([string]$ko, [string]$en) { Get-AxLabel -Ko $ko -En $en -Bilingual $bi }

    #region 선택지
    $choices = @{
        Entity           = @($Config.entities | ForEach-Object { [pscustomobject]@{ Key = $_; En = $null; Label = $_ } })
        AppType          = @(New-AxChoiceSet -Bilingual $bi -Pairs @(
                @('웹앱', 'Web app'), @('스크립트·자동화', 'Script/Automation'), @('엑셀·매크로', 'Excel/Macro'),
                @('RPA'), @('기타', 'Other')))
        UserScope        = @(New-AxChoiceSet -Bilingual $bi -Pairs @(
                @('본인만', 'Only me'), @('팀 공용', 'Team'), @('법인 공용', 'Entity-wide'), @('법인 간 공용', 'Cross-entity')))
        ConnectedSystems = @(New-AxChoiceSet -Bilingual $bi -Pairs @(
                @('없음', 'None'), @('ERP'), @('MES'), @('그룹웨어', 'Groupware'), @('외부 서비스', 'External service'), @('기타', 'Other')))
        RunLocation      = @(New-AxChoiceSet -Bilingual $bi -Pairs @(
                @('개인 PC', 'Personal PC'), @('사내 서버', 'On-premises server'), @('회사 클라우드', 'Company cloud'), @('외부 클라우드', 'External cloud')))
        Grade            = @(New-AxChoiceSet -Bilingual $bi -Pairs @(@('A'), @('B'), @('C')))
        Status           = @(New-AxChoiceSet -Bilingual $bi -Pairs @(
                @('접수', 'Submitted'), @('검토 중', 'In review'), @('보완 요청', 'Changes requested'), @('승인', 'Approved'),
                @('반려', 'Rejected'), @('사용 중단', 'Suspended'), @('폐기', 'Retired')))
        RequestType      = @(New-AxChoiceSet -Bilingual $bi -Pairs @(
                @('정보 변경', 'Info change'), @('담당자 변경', 'Owner change'), @('등급 재판정', 'Re-grade'),
                @('사용 중단', 'Suspend'), @('폐기', 'Retire')))
        RequestStatus    = @(New-AxChoiceSet -Bilingual $bi -Pairs @(
                @('접수', 'Submitted'), @('처리 완료', 'Done'), @('반려', 'Rejected')))
    }
    if ($Config.ContainsKey('includeRpa') -and -not $Config.includeRpa) {
        # D9: 기존 RPA 과제를 넣지 않기로 하면 선택지에서 뺀다 (기본: 넣음)
        $choices.AppType = @($choices.AppType | Where-Object Key -ne 'RPA')
    }
    function C([string]$field, [string]$key) { ($choices[$field] | Where-Object Key -eq $key).Label }
    #endregion

    #region 등급 수식 (5.3)
    $scopeSelf = C UserScope '본인만'
    $scopeCross = C UserScope '법인 간 공용'
    # {0}=[HasSensitiveData] {1}=[WritesToCore] {2}=[UserScope] {3}=[HasInternalData] — 실제 표시 이름으로 채운다 (02-lists.ps1)
    $formulaTemplate = '=IF(OR({0},{1},{2}="' + $scopeCross + '"),"C",IF(OR({3},{2}<>"' + $scopeSelf + '"),"B","A"))'
    $formulaRefs = @('HasSensitiveData', 'WritesToCore', 'UserScope', 'HasInternalData')
    #endregion

    #region 목록 1: 프로그램 등록부
    # Form = 양식에 켜는 열. Required 는 SharePoint 열의 필수 여부.
    # 예/아니오 열은 SharePoint에서 필수로 지정할 수 없고 항상 값(기본 아니오)이 있으므로 Required=$false, FormRequired=$true 로 둔다.
    $registryFields = @(
        @{ Name = 'Title'; Display = (L '프로그램명' 'Program name'); Type = 'Text'; Required = $true; Form = $true; Builtin = $true }
        @{ Name = 'Purpose'; Display = (L '용도 설명' 'Purpose'); Type = 'Note'; Required = $true; Form = $true; Description = '무슨 업무를 어떻게 줄이는지 적습니다.' }
        @{ Name = 'Entity'; Display = (L '법인' 'Entity'); Type = 'Choice'; Required = $true; Form = $true; Choices = 'Entity' }
        @{ Name = 'Dept'; Display = (L '팀' 'Team'); Type = 'Text'; Required = $true; Form = $true }
        @{ Name = 'Developer'; Display = (L '만든 사람' 'Developer'); Type = 'User'; Required = $true; Form = $true }
        @{ Name = 'OwnerManager'; Display = (L '책임 팀장' 'Accountable manager'); Type = 'User'; Required = $true; Form = $true }
        @{ Name = 'AppType'; Display = (L '형태' 'Type'); Type = 'Choice'; Required = $true; Form = $true; Choices = 'AppType' }
        @{ Name = 'BuildTool'; Display = (L '개발 도구' 'Build tool'); Type = 'Text'; Required = $false; Form = $true; Description = '사용한 AI 도구 이름' }
        @{ Name = 'UserScope'; Display = (L '사용 범위' 'User scope'); Type = 'Choice'; Required = $true; Form = $true; Choices = 'UserScope' }
        @{ Name = 'UserCount'; Display = (L '사용자 수' 'User count'); Type = 'Number'; Required = $false; Form = $true; Decimals = 0; Min = 0 }
        @{ Name = 'HasInternalData'; Display = (L '내부 업무 데이터 사용' 'Uses internal business data'); Type = 'Boolean'; Required = $false; FormRequired = $true; Form = $true; Default = '0'; Description = '오더, 생산 등' }
        @{ Name = 'HasSensitiveData'; Display = (L '개인정보·단가·재무 데이터 사용' 'Uses personal/price/financial data'); Type = 'Boolean'; Required = $false; FormRequired = $true; Form = $true; Default = '0' }
        @{ Name = 'DataNote'; Display = (L '다루는 데이터 설명' 'Data description'); Type = 'Note'; Required = $false; Form = $true; Description = '실제 데이터는 적지 않습니다.' }
        @{ Name = 'ConnectedSystems'; Display = (L '연결 시스템' 'Connected systems'); Type = 'MultiChoice'; Required = $true; Form = $true; Choices = 'ConnectedSystems' }
        @{ Name = 'WritesToCore'; Display = (L 'ERP·MES에 데이터 입력' 'Writes to ERP/MES'); Type = 'Boolean'; Required = $false; FormRequired = $true; Form = $true; Default = '0' }
        @{ Name = 'RunLocation'; Display = (L '실행 위치' 'Run location'); Type = 'Choice'; Required = $true; Form = $true; Choices = 'RunLocation' }
        @{ Name = 'CodeLocation'; Display = (L '코드·파일 위치' 'Code/file location'); Type = 'Text'; Required = $false; Form = $true; Description = '경로 또는 링크' }
        @{ Name = 'HoursSavedMonthly'; Display = (L '월 절감 시간' 'Hours saved per month'); Type = 'Number'; Required = $false; Form = $true; Decimals = 1; Min = 0; Description = '시간 단위' }
        # 시스템·검토자 열 (양식에서 제외)
        @{ Name = 'AutoGrade'; Display = (L '자동 판정 등급' 'Auto grade'); Type = 'Calculated'; Required = $false; Form = $false; FallbackType = 'Choice'; Choices = 'Grade' }
        @{ Name = 'Grade'; Display = (L '확정 등급' 'Final grade'); Type = 'Choice'; Required = $false; Form = $false; Choices = 'Grade' }
        @{ Name = 'Status'; Display = (L '상태' 'Status'); Type = 'Choice'; Required = $false; Form = $false; Choices = 'Status'; Default = (C Status '접수') }
        @{ Name = 'Reviewer'; Display = (L '검토자' 'Reviewer'); Type = 'User'; Required = $false; Form = $false }
        @{ Name = 'ReviewNote'; Display = (L '검토 의견' 'Review note'); Type = 'Note'; Required = $false; Form = $false }
        @{ Name = 'ApprovedDate'; Display = (L '승인일' 'Approved date'); Type = 'DateTime'; Required = $false; Form = $false }
        @{ Name = 'NextReviewDate'; Display = (L '다음 점검일' 'Next review date'); Type = 'DateTime'; Required = $false; Form = $false }
    )
    #endregion

    #region 목록 2: 변경 신청
    $changeFields = @(
        @{ Name = 'Title'; Display = (L '요청 제목' 'Request title'); Type = 'Text'; Required = $true; Form = $true; Builtin = $true }
        @{ Name = 'AppRegNo'; Display = (L '등록번호' 'Registration no.'); Type = 'Number'; Required = $true; Form = $true; Decimals = 0; Min = 1; Description = '프로그램 등록부의 ID' }
        @{ Name = 'RequestType'; Display = (L '유형' 'Request type'); Type = 'Choice'; Required = $true; Form = $true; Choices = 'RequestType' }
        @{ Name = 'Detail'; Display = (L '변경 내용' 'Details'); Type = 'Note'; Required = $true; Form = $true }
        @{ Name = 'RequestStatus'; Display = (L '처리 상태' 'Request status'); Type = 'Choice'; Required = $false; Form = $false; Choices = 'RequestStatus'; Default = (C RequestStatus '접수') }
        @{ Name = 'HandledBy'; Display = (L '처리자' 'Handled by'); Type = 'User'; Required = $false; Form = $false }
        @{ Name = 'HandledNote'; Display = (L '처리 의견' 'Handling note'); Type = 'Note'; Required = $false; Form = $false }
    )
    #endregion

    #region 라이브러리: 프로그램 자료
    $docFields = @(
        @{ Name = 'AppRegNo'; Display = (L '등록번호' 'Registration no.'); Type = 'Number'; Required = $false; Form = $false; Decimals = 0; Min = 1 }
    )
    #endregion

    $lists = [ordered]@{
        Registry = @{ Key = 'Registry'; Url = 'Lists/AppRegistry'; Title = (L '프로그램 등록부' 'App Registry'); Template = 'GenericList'
            Versioning = $true; MajorVersions = 50; Attachments = $false; Fields = $registryFields }
        Change   = @{ Key = 'Change'; Url = 'Lists/ChangeRequests'; Title = (L '변경 신청' 'Change Requests'); Template = 'GenericList'
            Attachments = $false; Fields = $changeFields }
        Docs     = @{ Key = 'Docs'; Url = 'AppDocs'; Title = (L '프로그램 자료' 'App Documents'); Template = 'DocumentLibrary'
            Fields = $docFields }
    }

    # 모든 정의에 같은 키가 있게 채운다 (StrictMode에서 없는 키를 읽으면 오류)
    $fieldKeys = 'Name', 'Display', 'Type', 'Required', 'FormRequired', 'Form', 'Builtin', 'Choices', 'Default', 'Description', 'Decimals', 'Min', 'FallbackType', 'Refs'
    foreach ($l in $lists.Values) {
        foreach ($k in 'Versioning', 'MajorVersions', 'Attachments') { if (-not $l.ContainsKey($k)) { $l[$k] = $null } }
        foreach ($f in $l.Fields) { foreach ($k in $fieldKeys) { if (-not $f.ContainsKey($k)) { $f[$k] = $null } } }
    }

    #region 보기 (5.3) — Url 은 영문으로 만들고 제목만 바꾼다
    $s = @{ Approved = (C Status '승인'); Submitted = (C Status '접수'); InReview = (C Status '검토 중'); Changes = (C Status '보완 요청') }
    $x = @{}; foreach ($k in $s.Keys) { $x[$k] = ConvertTo-AxXmlTextLocal $s[$k] }
    $days = [int]$Config.review.reminderDaysBefore
    $allFields = @('ID', 'LinkTitle') + @($registryFields | Where-Object { $_.Name -ne 'Title' } | ForEach-Object { $_.Name }) + @('Author', 'Created', 'Modified')
    $views = @(
        @{ Key = 'Catalog'; Title = (L '카탈로그' 'Catalog'); Default = $true
            Fields = @('LinkTitle', 'Purpose', 'Entity', 'Dept', 'Developer', 'Grade', 'UserScope')
            Query = "<Where><Eq><FieldRef Name='Status'/><Value Type='Choice'>$($x.Approved)</Value></Eq></Where><OrderBy><FieldRef Name='Title' Ascending='TRUE'/></OrderBy>" }
        @{ Key = 'ReviewQueue'; Title = (L '검토 대기' 'Review queue')
            Fields = @('ID', 'LinkTitle', 'Entity', 'AutoGrade', 'Status', 'Reviewer', 'Created')
            Query = "<Where><In><FieldRef Name='Status'/><Values><Value Type='Choice'>$($x.Submitted)</Value><Value Type='Choice'>$($x.InReview)</Value><Value Type='Choice'>$($x.Changes)</Value></Values></In></Where><OrderBy><FieldRef Name='Created' Ascending='TRUE'/></OrderBy>" }
        @{ Key = 'ByEntity'; Title = (L '법인별' 'By entity')
            Fields = @('LinkTitle', 'Dept', 'Grade', 'Status')
            Query = "<GroupBy Collapse='FALSE' GroupLimit='100'><FieldRef Name='Entity'/></GroupBy><OrderBy><FieldRef Name='Entity' Ascending='TRUE'/><FieldRef Name='Title' Ascending='TRUE'/></OrderBy>" }
        @{ Key = 'ReviewDue'; Title = (L '점검 예정' 'Review due')
            Fields = @('LinkTitle', 'Developer', 'OwnerManager', 'NextReviewDate')
            # 기한이 이미 지난 항목도 함께 보인다 (다음 점검일 <= 오늘+N일)
            Query = "<Where><And><Eq><FieldRef Name='Status'/><Value Type='Choice'>$($x.Approved)</Value></Eq><Leq><FieldRef Name='NextReviewDate'/><Value Type='DateTime'><Today OffsetDays='$days'/></Value></Leq></And></Where><OrderBy><FieldRef Name='NextReviewDate' Ascending='TRUE'/></OrderBy>" }
        @{ Key = 'MyApps'; Title = (L '내 프로그램' 'My programs')
            Fields = @('LinkTitle', 'Status', 'Grade', 'ReviewNote')
            Query = "<Where><Eq><FieldRef Name='Developer' LookupId='TRUE'/><Value Type='Integer'><UserID Type='Integer'/></Value></Eq></Where><OrderBy><FieldRef Name='Created' Ascending='FALSE'/></OrderBy>" }
        @{ Key = 'AdminAll'; Title = (L '전체(관리)' 'All (admin)')
            Fields = $allFields
            Query = "<OrderBy><FieldRef Name='ID' Ascending='FALSE'/></OrderBy>" }
    )
    foreach ($v in $views) { if (-not $v.ContainsKey('Default')) { $v.Default = $false } }
    #endregion

    #region 전수 조사 CSV 머리글 (data/survey-template.csv) → 내부 이름
    $surveyColumns = [ordered]@{
        '프로그램명'                       = 'Title'
        '용도 설명'                        = 'Purpose'
        '법인'                             = 'Entity'
        '팀'                               = 'Dept'
        '만든 사람(메일)'                  = 'Developer'
        '책임 팀장(메일)'                  = 'OwnerManager'
        '형태'                             = 'AppType'
        '개발 도구'                        = 'BuildTool'
        '사용 범위'                        = 'UserScope'
        '사용자 수'                        = 'UserCount'
        '내부 업무 데이터 사용'            = 'HasInternalData'
        '개인정보·단가·재무 데이터 사용'   = 'HasSensitiveData'
        '다루는 데이터 설명'               = 'DataNote'
        '연결 시스템'                      = 'ConnectedSystems'
        'ERP·MES에 데이터 입력'            = 'WritesToCore'
        '실행 위치'                        = 'RunLocation'
        '코드·파일 위치'                   = 'CodeLocation'
        '월 절감 시간'                     = 'HoursSavedMonthly'
    }
    #endregion

    #region 테스트 사례 (7.1)
    $testCases = @(
        @{ Title = '개인 파일 정리 도구'; Scope = '본인만'; Internal = $false; Sensitive = $false; Core = $false; Expected = 'A' }
        @{ Title = '개인용 오더 조회'; Scope = '본인만'; Internal = $true; Sensitive = $false; Core = $false; Expected = 'B' }
        @{ Title = '팀 서식 변환기'; Scope = '팀 공용'; Internal = $false; Sensitive = $false; Core = $false; Expected = 'B' }
        @{ Title = '법인 생산 리포트'; Scope = '법인 공용'; Internal = $true; Sensitive = $false; Core = $false; Expected = 'B' }
        @{ Title = '개인용 단가 비교'; Scope = '본인만'; Internal = $false; Sensitive = $true; Core = $false; Expected = 'C' }
        @{ Title = 'ERP 자동 입력'; Scope = '팀 공용'; Internal = $true; Sensitive = $false; Core = $true; Expected = 'C' }
        @{ Title = '전 법인 공용 도구'; Scope = '법인 간 공용'; Internal = $false; Sensitive = $false; Core = $false; Expected = 'C' }
    )
    #endregion

    return @{
        Bilingual       = $bi
        Choices         = $choices
        Lists           = $lists
        Views           = $views
        FormulaTemplate = $formulaTemplate
        FormulaRefs     = $formulaRefs
        TestCases       = $testCases
        SurveyColumns   = $surveyColumns
        TestPrefix      = '[TEST] '
        Groups          = @{ Reviewers = 'AX 검토자' }
        Pages           = @{ Home = 'AppCenterHome.aspx'; Grades = 'GradeCriteria.aspx' }
    }
}

function ConvertTo-AxXmlTextLocal {
    param([AllowEmptyString()][string]$Text)
    return [System.Security.SecurityElement]::Escape($Text)
}

function Get-AxExpectedGrade {
    <#
      5.3 등급 규칙의 PowerShell 구현. 계산 열 수식과 같은 규칙이며,
      계산 열이 실패해 F1에서 등급을 채우는 경우와 오프라인 점검에서 기준으로 쓴다.
      ScopeKey 는 사용 범위의 한국어 키 ('본인만', '팀 공용', '법인 공용', '법인 간 공용').
    #>
    param([Parameter(Mandatory)][string]$ScopeKey, [bool]$Internal, [bool]$Sensitive, [bool]$Core)
    if ($Sensitive -or $Core -or $ScopeKey -eq '법인 간 공용') { return 'C' }
    if ($Internal -or $ScopeKey -ne '본인만') { return 'B' }
    return 'A'
}

function Get-AxFieldXml {
    <#
      열 정의 → SharePoint Field XML. 처음 만들 때 DisplayName 은 내부 이름과 같게 둔다
      (표시 이름은 02-lists.ps1 이 나중에 바꾼다). Calculated 는 Formula 를 따로 받는다.
    #>
    param([Parameter(Mandatory)][hashtable]$Field, [hashtable]$Choices, [string]$Formula, [string]$TypeOverride)

    $type = if ($TypeOverride) { $TypeOverride } else { $Field.Type }
    $n = $Field.Name
    $req = if ($Field.Required) { 'TRUE' } else { 'FALSE' }
    $attrs = "Name=`"$n`" StaticName=`"$n`" DisplayName=`"$n`" Required=`"$req`""
    $inner = ''

    switch ($type) {
        'Text' { $attrs = "Type=`"Text`" $attrs MaxLength=`"255`"" }
        'Note' { $attrs = "Type=`"Note`" $attrs NumLines=`"6`" RichText=`"FALSE`" UnlimitedLengthInDocumentLibrary=`"FALSE`"" }
        'Number' {
            $attrs = "Type=`"Number`" $attrs"
            if ($null -ne $Field.Decimals) { $attrs += " Decimals=`"$($Field.Decimals)`"" }
            if ($null -ne $Field.Min) { $attrs += " Min=`"$($Field.Min)`"" }
        }
        'Boolean' { $attrs = "Type=`"Boolean`" $attrs" }
        'DateTime' { $attrs = "Type=`"DateTime`" $attrs Format=`"DateOnly`"" }
        'User' { $attrs = "Type=`"User`" $attrs UserSelectionMode=`"PeopleOnly`" UserSelectionScope=`"0`" ShowField=`"ImnName`" List=`"UserInfo`"" }
        { $_ -in 'Choice', 'MultiChoice' } {
            $fmt = if ($type -eq 'Choice') { ' Format="Dropdown" FillInChoice="FALSE"' } else { ' FillInChoice="FALSE"' }
            $attrs = "Type=`"$type`" $attrs$fmt"
            $items = ($Choices[$Field.Choices] | ForEach-Object { '<CHOICE>' + (ConvertTo-AxXmlTextLocal $_.Label) + '</CHOICE>' }) -join ''
            $inner += "<CHOICES>$items</CHOICES>"
        }
        'Calculated' {
            $attrs = "Type=`"Calculated`" $attrs ResultType=`"Text`" ReadOnly=`"TRUE`""
            $inner += '<Formula>' + (ConvertTo-AxXmlTextLocal $Formula) + '</Formula>'
            $inner += '<FieldRefs>' + (($Field.Refs | ForEach-Object { "<FieldRef Name=`"$_`"/>" }) -join '') + '</FieldRefs>'
        }
        default { throw "알 수 없는 열 형식: $type ($n)" }
    }
    if ($null -ne $Field.Default -and $type -ne 'Calculated') {
        $inner += '<Default>' + (ConvertTo-AxXmlTextLocal ([string]$Field.Default)) + '</Default>'
    }
    if (-not $Field.Form -and -not $Field.Builtin) {
        # 기본(클래식) 새 항목 화면에서는 숨긴다. Lists 양식은 docs/manual-form.md 대로 사람이 끈다.
        $attrs += ' ShowInNewForm="FALSE"'
    }
    return "<Field $attrs>$inner</Field>"
}
