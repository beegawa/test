<#
.SYNOPSIS
  6단계: 권한 그룹과 목록 권한 (기획서 5.2).
.DESCRIPTION
  그룹          구성원                             사이트     등록부·변경 신청·자료
  소유자(연결)  config.people.owners               모든 권한  모든 권한
  AX 검토자     reviewers + 보안 + 시스템 담당     읽기       편집
  방문자(연결)  외부 사용자를 제외한 모든 사용자   읽기       읽기
  - 소유자·방문자 그룹은 사이트에 연결된 기본 그룹을 쓴다 (이름은 사이트 언어에 따라 다름).
  - 등록부, 변경 신청, 자료 라이브러리는 권한 상속을 끊는다. 이 세 곳에서 구성원(Members) 그룹 권한은 뺀다.
  - 그룹 구성원은 추가만 한다. 설정에 없는 구성원은 경고만 남긴다.
  - config.permissions.visitorsCanSubmit=true 면 (8장 대안) 방문자에게 등록부·변경 신청 기여 권한을 주고
    쓰기 보안을 WriteOnlyMyItems 로 둔다. 이 경우 F1에서 등급·상태 되돌림이 필요하다.
#>
[CmdletBinding(SupportsShouldProcess)]
param([string]$ConfigPath)

. "$PSScriptRoot/lib/common.ps1"

$ctx = Initialize-AxStep -ConfigPath $ConfigPath -WhatIf ([bool]$WhatIfPreference)
$cfg = $ctx.Config; $schema = $ctx.Schema
$submit = [bool]$cfg.permissions.visitorsCanSubmit
Write-AxStep '04 권한'

# 목록별 원하는 역할 (RoleTypeKind)
$desired = [ordered]@{}
foreach ($l in $schema.Lists.Values) {
    $visitorRole = if ($submit -and $l.Key -in 'Registry', 'Change') { 'Contributor' } else { 'Reader' }
    $desired[$l.Url] = @{ Owners = 'Administrator'; Reviewers = 'Editor'; Visitors = $visitorRole }
}

if ($ctx.PlanOnly) {
    Write-AxLog PLAN "그룹 '$($schema.Groups.Reviewers)' 확인/생성, 소유자 그룹 = 사이트 기본 소유자 그룹, 방문자 그룹 = 사이트 기본 방문자 그룹"
    Write-AxLog PLAN "소유자 그룹 구성원 추가: $(@($cfg.people.owners) -join ', ')"
    Write-AxLog PLAN "검토자 그룹 구성원 추가: $((Get-AxAllPeople -Config $cfg) -join ', ')"
    Write-AxLog PLAN '방문자 그룹 구성원 추가: c:0-.f|rolemanager|spo-grid-all-users/<tenantId> (외부 사용자를 제외한 모든 사용자)'
    Write-AxLog PLAN '사이트 권한: 검토자 그룹 = 읽기'
    foreach ($k in $desired.Keys) {
        $d = $desired[$k]
        Write-AxLog PLAN "목록 $k : 상속 끊기, 소유자=$($d.Owners) 검토자=$($d.Reviewers) 방문자=$($d.Visitors) 구성원=없음"
    }
    if ($submit) { Write-AxLog PLAN '쓰기 보안 WriteOnlyMyItems: Lists/AppRegistry, Lists/ChangeRequests (8장 대안 사용 중)' }
    return
}

Assert-AxSafeTarget -Config $cfg
$roles = Get-AxRoleNames   # RoleTypeKind -> 이 사이트 언어의 역할 이름
$web = Get-PnPWeb

#region 그룹
$owners = Get-PnPGroup -AssociatedOwnerGroup
$visitors = Get-PnPGroup -AssociatedVisitorGroup
$members = $null
try { $members = Get-PnPGroup -AssociatedMemberGroup } catch { $members = $null }

$reviewers = Get-PnPGroup -Identity $schema.Groups.Reviewers -ErrorAction SilentlyContinue
if (-not $reviewers -and $PSCmdlet.ShouldProcess($schema.Groups.Reviewers, 'New-PnPGroup')) {
    $reviewers = New-PnPGroup -Title $schema.Groups.Reviewers -Owner $owners.Title -Description 'AX 앱 센터 검토자: 법인별 AX 담당자, 정보보안 담당, 시스템 담당'
    Write-AxLog CHANGE "그룹을 만들었습니다: $($schema.Groups.Reviewers)"
}
elseif ($reviewers) { Write-AxLog SKIP "그룹이 이미 있습니다: $($schema.Groups.Reviewers)" }
#endregion

#region 그룹 구성원 (추가만)
function Add-AxMembers {
    param($Group, [string[]]$Logins, [string]$Label)
    if (-not $Group) { return }
    $existing = @(Get-PnPGroupMember -Group $Group.Title)
    $keys = @($existing | ForEach-Object { @([string]$_.Email, [string]$_.LoginName) } | Where-Object { $_ } | ForEach-Object { $_.ToLowerInvariant() })
    foreach ($login in $Logins) {
        $l = $login.ToLowerInvariant()
        if ($keys | Where-Object { $_ -eq $l -or $_.EndsWith("|$l") }) { Write-AxLog SKIP "$Label 구성원 있음: $login"; continue }
        if ($PSCmdlet.ShouldProcess($Group.Title, "Add-PnPGroupMember $login")) {
            Add-PnPGroupMember -Group $Group.Title -LoginName $login
            Write-AxLog CHANGE "$Label 구성원 추가: $login"
        }
    }
    $want = @($Logins | ForEach-Object { $_.ToLowerInvariant() })
    foreach ($m in $existing) {
        $ids = @([string]$m.Email, [string]$m.LoginName) | Where-Object { $_ } | ForEach-Object { $_.ToLowerInvariant() }
        $known = $ids | Where-Object { $id = $_; $want | Where-Object { $id -eq $_ -or $id.EndsWith("|$_") } }
        if (-not $known -and $m.LoginName -notmatch 'SHAREPOINT\\system') { Write-AxLog WARN "$Label 에 설정에 없는 구성원이 있습니다 (지우지 않음): $($m.LoginName)" }
    }
}

$tenantId = Get-PnPTenantId
$everyone = "c:0-.f|rolemanager|spo-grid-all-users/$tenantId"
Add-AxMembers -Group $owners -Logins @($cfg.people.owners) -Label '소유자 그룹'
Add-AxMembers -Group $reviewers -Logins (Get-AxAllPeople -Config $cfg) -Label '검토자 그룹'
Add-AxMembers -Group $visitors -Logins @($everyone) -Label '방문자 그룹'
if ($members) {
    $mm = @(Get-PnPGroupMember -Group $members.Title)
    if ($mm.Count) { Write-AxLog WARN "구성원 그룹 '$($members.Title)'에 $($mm.Count)명이 있습니다. 사이트 편집 권한이 있으니 확인하세요 (등록부 등 세 목록에서는 권한이 빠집니다)." }
}
#endregion

#region 역할 할당 헬퍼
function Get-AxAssignedRoleKinds {
    param([scriptblock]$Getter)
    try { return @(& $Getter | ForEach-Object { [string]$_.RoleTypeKind }) } catch { return @() }
}

function Set-AxListRole {
    param([string]$ListUrl, $Group, [string]$WantKind)
    $have = Get-AxAssignedRoleKinds { Get-PnPListPermissions -Identity $ListUrl -PrincipalId $Group.Id }
    $manageable = @($have | Where-Object { $_ -notin 'Guest', 'None' })   # 제한된 액세스는 손대지 않는다
    if ($WantKind -and $WantKind -notin $have -and $PSCmdlet.ShouldProcess("$ListUrl / $($Group.Title)", "역할 추가 $($roles[$WantKind])")) {
        Set-PnPListPermission -Identity $ListUrl -Group $Group.Title -AddRole $roles[$WantKind]
        Write-AxLog CHANGE "$ListUrl / $($Group.Title): $($roles[$WantKind]) 부여"
    }
    foreach ($k in $manageable | Where-Object { $_ -ne $WantKind }) {
        $name = $roles[$k]
        if (-not $name) { Write-AxLog WARN "$ListUrl / $($Group.Title): 알 수 없는 역할 $k (그대로 둠)"; continue }
        if ($PSCmdlet.ShouldProcess("$ListUrl / $($Group.Title)", "역할 제거 $name")) {
            Set-PnPListPermission -Identity $ListUrl -Group $Group.Title -RemoveRole $name
            Write-AxLog CHANGE "$ListUrl / $($Group.Title): $name 제거"
        }
    }
    if ($WantKind -in $have -and $manageable.Count -eq 1) { Write-AxLog SKIP "$ListUrl / $($Group.Title): $($roles[$WantKind]) 이미 있음" }
}
#endregion

#region 사이트 권한: 검토자 = 읽기
if ($reviewers) {
    $have = Get-AxAssignedRoleKinds { Get-PnPWebPermission -Identity $web -PrincipalId $reviewers.Id }
    if ('Reader' -notin $have -and $PSCmdlet.ShouldProcess('사이트', "$($reviewers.Title) 에 $($roles.Reader)")) {
        Set-PnPWebPermission -Group $reviewers.Title -AddRole $roles.Reader
        Write-AxLog CHANGE "사이트: $($reviewers.Title) 에 $($roles.Reader) 부여"
    }
    else { Write-AxLog SKIP "사이트: $($reviewers.Title) 읽기 권한 있음" }
}
#endregion

#region 목록 권한
foreach ($url in $desired.Keys) {
    $list = Get-PnPList -Identity $url -Includes HasUniqueRoleAssignments, WriteSecurity -ErrorAction SilentlyContinue
    if (-not $list) { Write-AxLog WARN "목록이 없습니다: $url (02-lists.ps1 먼저)"; continue }

    if (-not $list.HasUniqueRoleAssignments -and $PSCmdlet.ShouldProcess($url, '권한 상속 끊기 (기존 권한 복사)')) {
        Set-PnPList -Identity $url -BreakRoleInheritance -CopyRoleAssignments | Out-Null
        Write-AxLog CHANGE "$url : 권한 상속을 끊었습니다"
    }
    $d = $desired[$url]
    Set-AxListRole -ListUrl $url -Group $owners -WantKind $d.Owners
    if ($reviewers) { Set-AxListRole -ListUrl $url -Group $reviewers -WantKind $d.Reviewers }
    Set-AxListRole -ListUrl $url -Group $visitors -WantKind $d.Visitors
    if ($members) { Set-AxListRole -ListUrl $url -Group $members -WantKind $null }

    if ($url -in $schema.Lists.Registry.Url, $schema.Lists.Change.Url) {
        $wantWs = if ($submit) { 2 } else { 1 }   # 1 = WriteAllItems, 2 = WriteOnlyMyItems
        if ([int]$list.WriteSecurity -ne $wantWs) {
            $name = if ($submit) { 'WriteOnlyMyItems' } else { 'WriteAllItems' }
            if ($PSCmdlet.ShouldProcess($url, "WriteSecurity=$name")) {
                Set-PnPList -Identity $url -WriteSecurity $name | Out-Null
                Write-AxLog CHANGE "$url : 쓰기 보안 $name"
            }
        }
    }
}
#endregion

Write-AxLog OK '권한 준비 완료'
