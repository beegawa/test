# 검증 기록

기획서 8장(확인하지 못한 사항)과 구현 중 나온 확인 항목의 결과를 남긴다.
결과 칸: `미확인` / `됨` / `안 됨 → 대안 적용` / `해당 없음`. 확인한 사람과 날짜를 함께 적는다.

## 1. 기획서 8장 항목 (실제 테넌트에서 확인)

| # | 항목 | 확인 방법 | 결과 | 확인자·날짜 | 비고 |
|---|---|---|---|---|---|
| 8-1 | 양식 제출 권한: 목록 읽기 권한만으로 Lists 양식 제출이 되는지 | `docs/manual-form.md` 1-5 | 미확인 | | 안 되면 `permissions.visitorsCanSubmit=true` → `04-permissions.ps1`, F1 8장 보호 단계 |
| 8-2 | 양식의 열 지원: 사용자·복수 선택·예/아니오 열이 양식에 나오는지 | 양식 만들 때 (manual-form 1-3) | 미확인 | | 안 되면 사람과 협의해 열 형식 변경 (스크립트는 자동으로 바꾸지 않음) |
| 8-3 | 계산 열: 예/아니오 열 참조 수식이 한국어 사이트에서 동작하는지 | `02-lists.ps1` 로그(“계산 열을 만들었습니다”) + `06-seed-test-data.ps1` → `99-verify.ps1 -Stage grade` | 미확인 | | 생성 실패 시 스크립트가 자동으로 선택 열 대안을 만들고 경고. F1 `Grade` 식이 같은 규칙으로 계산 |
| 8-4 | 한/영 병기: 병기 선택지 문자열이 수식과 보기 필터에서 문제없는지 | 8-3 결과 + `카탈로그`·`검토 대기` 보기에 해당 항목이 나오는지 | 미확인 | | 문제가 있으면 `labels.bilingual=false`. 단, 이미 만든 선택지는 지우지 않으므로 목록 설정에서 사람이 정리 |
| 8-5 | 목록 웹 파트: 스크립트로 넣은 웹 파트가 `카탈로그` 보기를 보여 주는지 | 홈 화면 확인 + `99-verify.ps1 -Stage pages` | 미확인 | | 웹 파트 속성(`selectedListId`, `selectedViewId` 등)은 공개 문서가 없어 일반적인 형식으로 넣었다. 실패 시 스크립트가 보기 링크로 대신 넣고, manual-form 3-6에서 수동 추가 |
| 8-6 | 기본 승인 기능(콘텐츠 승인)이 F1을 대신할 수 있는지 | — | 해당 없음 | 기획 | 기획서 결정: 등급별 분기가 필요해 쓰지 않음. 스크립트도 켜지 않음 |
| 8-7 | 라이선스: 요금제에 Power Automate 표준 커넥터와 승인이 포함되는지 | IT 확인 | 미확인 | | |

## 2. 구현 중 나온 확인 항목

| # | 항목 | 확인 방법 | 결과 | 확인자·날짜 | 비고 |
|---|---|---|---|---|---|
| I-1 | 설치된 PnP.PowerShell 버전의 cmdlet 매개변수 | 실행 전에 `Get-Help <cmdlet> -Full` (아래 3-2 목록) | 미확인 | | 작성 시점에는 pnp/powershell GitHub 문서로만 확인 (3-2) |
| I-2 | Button 웹 파트 속성 이름 (`label`/`title`, `linkUrl`, `alignment`) | 홈에서 버튼 글자·링크가 보이는지 | 미확인 | | 공개 문서가 없어 `label`과 `title`을 함께 넣었다. 실패 시 텍스트 링크로 대신. 어차피 manual-form 3장에서 링크를 손으로 바꾼다 |
| I-3 | `Get-PnPListPermissions`·`Get-PnPWebPermission`이 권한이 없는 주체에서 오류를 내는지, 빈 값을 내는지 | `04-permissions.ps1` 첫 실행 | 미확인 | | 두 경우 모두 "역할 없음"으로 처리하게 했다 |
| I-4 | 사이트 존재 확인: 루트 연결로 `<site>/_api/web` 호출 시 없는 사이트에서 404가 나는지 | `01-site.ps1` 첫 실행 | 미확인 | | 404가 아니라 다른 오류면 스크립트가 멈추고 메시지를 보여 준다 |
| I-5 | Choice 열 기본값, 예/아니오 기본값(`0`)이 XML대로 들어가는지 | `99-verify.ps1 -Stage lists` + 새 항목의 상태가 `접수`인지 | 미확인 | | |
| I-6 | `ShowInNewForm="FALSE"`로 숨긴 시스템 열이 Lists 양식에는 영향을 주지 않는지 | 양식 만들 때 | 미확인 | | 클래식 새 항목 화면에서만 숨기려는 목적. 양식에서는 manual-form 1-3대로 사람이 끈다 |
| I-7 | F1 `ValidateUpdateListItem` 본문에 따옴표·줄바꿈이 든 검토 의견이 문제없이 들어가는지 | 반려 의견에 `"테스트"`와 줄바꿈을 넣어 확인 | 미확인 | | 작성 동작(객체) 출력을 그대로 넘기면 자동 이스케이프되는 것으로 알고 있음 |
| I-8 | F1 날짜 값 형식(`yyyy-MM-dd`)이 사이트 지역 설정에서 받아들여지는지 | A등급 테스트 제출 후 승인일·다음 점검일 | 미확인 | | 실패 시 `Check update`가 GBI팀에 메일 |
| I-9 | 구성원(Members) 그룹 처리: 세 목록에서 권한을 빼는 것이 운영 방침과 맞는지 | GBI팀 확인 | 미확인 | | 기획서 5.2 표에 구성원 그룹이 없어 뺐다. 사이트 수준 편집 권한은 그대로 두고, 구성원이 있으면 경고 |

## 3. 이 저장소에서 확인한 것 (2026-10-02, 테넌트 연결 없음)

### 3-1. 오프라인 실행

PowerShell 7.4.6 (Linux)에서 실행.

| 확인 | 결과 |
|---|---|
| `./deploy.ps1 -WhatIf -ConfigPath ../config/config.sample.json` | 연결 없이 01~05 실행 계획 출력, 빈 설정 값 경고 (완료 기준 1단계) |
| `./99-verify.ps1 -Offline` (병기 / 한국어만 두 설정) | 실패 0. 열 XML 33개, 보기 CAML 6개 파싱, CSV 머리글 일치 |
| 등급 수식 | 생성한 수식 문자열을 `lib/formula.ps1` 해석기로 계산해 7.1 표 7개 사례 모두 기대 등급과 같음 (병기·한국어만 모두) |
| `./07-import-survey.ps1 -WhatIf` | 오류 행(빈 필수, 없는 선택지, 메일 형식, 예/아니오 아님) 검출, 영어 선택지 값 인식, 파일 안 중복 검출 |
| 모든 `.ps1` 구문 분석 | 오류 0 |

### 3-2. 가짜 PnP 모듈로 흐름 점검

PSGallery에 접근할 수 없는 환경이라 실제 PnP.PowerShell 대신 메모리 상태를 흉내 내는 가짜 모듈로 전체 순서를 돌렸다. **실제 SharePoint 동작을 증명하지는 않는다.** 스크립트 논리(StrictMode 오류, 멱등성, 분기)를 점검하는 용도다.

| 시나리오 | 결과 |
|---|---|
| deploy → seed → verify → import ×2 → deploy 재실행 → seed 재실행 | verify 실패 0. 두 번째 deploy·seed에서 변경 0건 (멱등). 두 번째 import 추가 0건 |
| 계산 열 생성 실패를 흉내 | 선택 열 대안 생성, verify가 "F1이 채운 뒤 다시 점검" 경고로 표시, 재실행 변경 0건 |
| `visitorsCanSubmit=true` | 방문자 기여 권한, 쓰기 보안 WriteOnlyMyItems 적용, verify 통과 |

### 3-3. cmdlet 매개변수 대조

github.com/pnp/powershell `documentation/*.md`(2026-10-02 기준 main)와 대조했다. 설치 버전에서 다시 확인한다 (I-1).

`Connect-PnPOnline`(-Interactive, -ClientId, -Connection), `Get-PnPConnection`, `New-PnPSite`(CommunicationSite: -Title -Url -Lcid), `Invoke-PnPSPRestMethod`, `Get-PnPWeb`/`Set-PnPWeb`, `Get-PnPList`(-Includes), `New-PnPList`(-Template -Url), `Set-PnPList`(-EnableVersioning -MajorVersions -EnableAttachments -EnableFolderCreation -BreakRoleInheritance -CopyRoleAssignments -WriteSecurity), `Get-PnPField`, `Add-PnPFieldFromXml`, `Set-PnPField`(-Values; 형식별 속성은 리플렉션으로 설정되고 실패는 경고만 남김 → verify로 확인), `Get-PnPView`/`Add-PnPView`(-Query는 `<Query>` 안쪽 CAML)/`Set-PnPView`(-Values, -Fields), `Get-PnPRoleDefinition`, `Get-PnPGroup`(-AssociatedOwnerGroup 등), `New-PnPGroup`, `Get-PnPGroupMember`, `Add-PnPGroupMember`(-LoginName), `Get-PnPTenantId`, `Get-PnPWebPermission`/`Set-PnPWebPermission`, `Get-PnPListPermissions`/`Set-PnPListPermission`, `Get-PnPPage`/`Add-PnPPage`/`Set-PnPPage`, `Add-PnPPageSection`, `Add-PnPPageTextPart`, `Add-PnPPageWebPart`(-DefaultWebPartType List/Button, -WebPartProperties는 JSON 문자열 가능), `Get-PnPPageComponent`, `Get-PnPHomePage`/`Set-PnPHomePage`, `Get-PnPListItem`/`Add-PnPListItem`/`Set-PnPListItem`, `Get-PnPProperty`.

## 4. 사람이 정할 값 (기획서 9장) 현황

| 번호 | 항목 | 상태 |
|---|---|---|
| D1 | 사이트 주소와 이름 | 기본안 사용 (`ax-app-center`, AX 앱 센터) |
| D2 | 법인 목록 | **미입력** |
| D3 | 언어 | 기본안 (한/영 병기) |
| D4 | 소유자·검토자·승인자 메일 | **미입력** |
| D5 | B등급 검토 기한 | 가정 5영업일 |
| D6 | 정기 점검 주기 | 가정 12개월 |
| D7 | 흐름 소유 공용 계정 | **미정** (IT 협의) |
| D8 | 검토 의견 공개 | 기본안 공개 |
| D9 | RPA 포함 | 기본안 포함 (`includeRpa: true`) |
| D10 | 법인별 AX 담당자 대응표 (F1 B등급 참조 알림) | **미정** — 기획서에 없던 항목 |
| D11 | F2 알림 Teams 팀·채널 | **미정** — 기획서에 없던 항목 |
| — | `tenant`, `clientId` | **미입력** (IT 앱 등록 후) |
