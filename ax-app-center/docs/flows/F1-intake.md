# F1 접수와 분류

등록부에 새 항목이 생기면 등급(A/B/C)에 따라 자동 승인하거나 승인 요청을 보낸다. (기획서 5.8)

- 종류: 자동화된 클라우드 흐름 (Automated cloud flow)
- 이름: `AX F1 접수와 분류`
- 커넥터: SharePoint, 승인(Approvals), Office 365 Outlook — 모두 표준
- 소유자: 공용 계정(D7). GBI팀 전원을 공동 소유자로 추가한다. 연결(Connection)도 공용 계정으로 만든다.
- 소요 시간: 약 20분 (이 문서를 따라 하는 경우)

## 0. 먼저 알아 둘 것

- **트리거는 "항목을 만든 경우"만 쓴다.** 흐름이 항목을 고쳐도 다시 실행되지 않아 무한 반복이 없다.
- **항목 수정은 "SharePoint에 HTTP 요청 보내기"의 `ValidateUpdateListItem` 하나로 한다.** "항목 업데이트" 동작은 필수 열 10개를 매번 다시 넣어야 해서 쓰지 않는다. 수정은 흐름 끝에서 한 번 + 검토 시작 때 한 번, 모두 두 번뿐이다.
- 아래 표의 **동작 이름**을 그대로 쓴다. 식(expression)이 동작 이름을 참조한다. 이름의 공백은 식에서 `_`가 된다 (`Get item` → `body('Get_item')`).
- 선택지 문자열은 한/영 병기 기준이다(`승인 / Approved`). 한국어만 쓰면 `Settings`의 `labels`만 한국어로 바꾼다.

## 1. 트리거

| 설정 | 값 |
|---|---|
| 트리거 | SharePoint · **항목을 만든 경우 (When an item is created)** |
| 사이트 주소 | `https://<tenant>.sharepoint.com/sites/ax-app-center` (테스트는 `ax-app-center-test`) |
| 목록 이름 | `프로그램 등록부` |

## 2. 동작 순서 한눈에

```
Settings (작성)
Get item (항목 가져오기)
Grade (작성)            ← 자동 판정 등급. 계산 열이 비어 있으면 같은 규칙으로 계산
Item link (작성)
Systems (선택)          ← 연결 시스템 값 목록 (메일·승인 문안용)
변수 초기화 ×5: vStatus, vGrade, vReviewer, vNote, vApproved
Switch on grade (스위치)
 ├ A: 변수 설정 (승인)
 ├ B: Set in review → Approval B → 결과에 따라 변수 설정, 법인 담당자 참조 메일
 └ C: Set in review → Approval security → Approval system → Approval GBI (앞 단계 반려 시 중단)
Update body (작성)
Update item (SharePoint에 HTTP 요청 보내기)
Notify developer (메일 보내기 V2)
```

## 3. 공통 동작

### 3-1. `Settings` — 작성 (Compose)

입력에 아래 JSON을 붙여 넣고 `<...>`를 실제 값으로 바꾼다. 여러 사람은 `;`로 잇는다.

```json
{
  "siteUrl": "https://<tenant>.sharepoint.com/sites/ax-app-center",
  "listPath": "/sites/ax-app-center/Lists/AppRegistry",
  "owners": "<GBI팀1@회사>;<GBI팀2@회사>",
  "security": "<정보보안 담당@회사>",
  "erp": "<ERP TFT 담당@회사>",
  "mes": "<스마트팩토리팀 담당@회사>",
  "si": "<SI팀 담당@회사>",
  "recheckMonths": 12,
  "entityContacts": {
    "<본사>": "<본사 AX 담당@회사>",
    "<법인 1>": "<법인 1 AX 담당@회사>"
  },
  "labels": {
    "inReview": "검토 중 / In review",
    "approved": "승인 / Approved",
    "rejected": "반려 / Rejected",
    "scopeSelf": "본인만 / Only me",
    "scopeCross": "법인 간 공용 / Cross-entity"
  }
}
```

- 값은 `config.json`의 `people`, `review.recheckMonths`와 같게 둔다.
- `entityContacts`의 키는 `config.json`의 `entities`와 글자까지 같아야 한다. 법인별 AX 담당자 대응표는 아직 정해지지 않았다 (D10).

### 3-2. `Get item` — SharePoint · 항목 가져오기 (Get item)

| 입력 | 값 |
|---|---|
| 사이트 주소 / 목록 이름 | 트리거와 같음 |
| ID | 동적 콘텐츠 `ID` (트리거) |

계산 열 값을 확실히 받으려고 다시 읽는다.

### 3-3. `Grade` — 작성

입력에 **식**으로 붙여 넣는다.

```
if(contains(createArray('A','B','C'), string(body('Get_item')?['AutoGrade'])),
   string(body('Get_item')?['AutoGrade']),
   if(or(equals(body('Get_item')?['HasSensitiveData'], true), equals(body('Get_item')?['WritesToCore'], true),
         equals(body('Get_item')?['UserScope']?['Value'], outputs('Settings')?['labels']?['scopeCross'])), 'C',
      if(or(equals(body('Get_item')?['HasInternalData'], true),
            not(equals(body('Get_item')?['UserScope']?['Value'], outputs('Settings')?['labels']?['scopeSelf']))), 'B', 'A')))
```

계산 열(`AutoGrade`)이 정상이면 그 값을, 계산 열 대안(선택 열)을 쓰는 중이라 비어 있으면 같은 규칙(기획서 5.3)으로 계산한다.

### 3-4. `Item link` — 작성

```
concat(outputs('Settings')?['siteUrl'], '/Lists/AppRegistry/DispForm.aspx?ID=', triggerOutputs()?['body/ID'])
```

### 3-5. 변수 초기화 (Initialize variable) 5개

| 이름 | 형식 | 초기값 |
|---|---|---|
| `vStatus` | 문자열 | (비움) |
| `vGrade` | 문자열 | (비움) |
| `vReviewer` | 문자열 | (비움) — 승인한 사람 메일 |
| `vNote` | 문자열 | (비움) — 검토 의견 누적 |
| `vApproved` | 부울 | `false` |

### 3-6. `Set in review` (B·C에서 사용) — SharePoint에 HTTP 요청 보내기

B와 C 분기 맨 앞에 같은 동작을 하나씩 둔다 (이름 `Set in review B`, `Set in review C`).

| 입력 | 값 |
|---|---|
| 사이트 주소 | `Settings`의 siteUrl (식 `outputs('Settings')?['siteUrl']`) |
| 방법 | `POST` |
| Uri | `_api/web/GetList('@{outputs('Settings')?['listPath']}')/items(@{triggerOutputs()?['body/ID']})/ValidateUpdateListItem()` |
| 헤더 | `Accept` = `application/json;odata=nometadata`, `Content-Type` = `application/json;odata=nometadata` |
| 본문 | 아래 |

```json
{
  "formValues": [
    { "FieldName": "Status", "FieldValue": "@{outputs('Settings')?['labels']?['inReview']}" }
  ],
  "bNewDocumentUpdate": false
}
```

## 4. `Switch on grade` — 스위치 (Switch)

켜기(On): `outputs('Grade')`

### 4-A. 경우 `A`

변수 설정 4개:

| 변수 | 값 |
|---|---|
| `vStatus` | `outputs('Settings')?['labels']?['approved']` |
| `vGrade` | `A` |
| `vApproved` | `true` |
| `vNote` | `A등급 자동 승인` |

### 4-B. 경우 `B`

1. `Set in review B` (3-6)
2. **법인 담당자 참조 알림** — 조건: `outputs('Settings')?['entityContacts']?[body('Get_item')?['Entity']?['Value']]` 이(가) 비어 있지 않음
   - 예: Office 365 Outlook · **메일 보내기 (V2)**
     - 받는 사람: 위 식
     - 제목: `[AX 앱 센터] B등급 검토 시작 (참조): @{body('Get_item')?['Title']}`
     - 본문: 7장 "B 참조 알림"
3. `Approval B` — 승인 · **승인 시작 및 대기 (Start and wait for an approval)**

   | 입력 | 값 |
   |---|---|
   | 승인 유형 | **승인/거부 - 첫 번째 응답자 (Approve/Reject - First to respond)** |
   | 제목 | `[AX 앱 센터] B등급 승인 요청 #@{triggerOutputs()?['body/ID']} @{body('Get_item')?['Title']}` |
   | 할당 대상 | `outputs('Settings')?['owners']` |
   | 세부 정보 | 7장 "승인 요청 세부 정보" |
   | 항목 링크 / 설명 | `outputs('Item link')` / `등록부에서 보기` |

4. `Note B` — 각각에 적용 (Apply to each) `body('Approval_B')?['responses']`
   - 문자열 변수에 추가 `vNote`: `[GBI] @{items('Note_B')?['approverResponse']} - @{items('Note_B')?['responder']?['displayName']}: @{items('Note_B')?['comments']}` 다음 줄 바꿈
5. 조건 `body('Approval_B')?['outcome']` 이(가) `Approve` 와 같음
   - 예: `vStatus` = approved 라벨, `vGrade` = `B`, `vApproved` = `true`, `vReviewer` = `first(body('Approval_B')?['responses'])?['responder']?['email']`
   - 아니요: `vStatus` = rejected 라벨, `vReviewer` = 같은 식

### 4-C. 경우 `C`

1. `Set in review C` (3-6)
2. `System approvers` — 작성. 연결 시스템 값(`Systems` 배열에 `ERP`, `MES`가 그대로 있는지)으로 시스템 담당을 정한다.

   ```
   if(and(contains(body('Systems'), 'ERP'), contains(body('Systems'), 'MES')),
      concat(outputs('Settings')?['erp'], ';', outputs('Settings')?['mes']),
      if(contains(body('Systems'), 'ERP'), outputs('Settings')?['erp'],
         if(contains(body('Systems'), 'MES'), outputs('Settings')?['mes'], outputs('Settings')?['si'])))
   ```

3. `Approval security` — 승인 시작 및 대기. 유형 **첫 번째 응답자**, 할당 대상 `outputs('Settings')?['security']`, 제목 `[AX 앱 센터] C등급 1/3 보안 검토 #...`
4. `Note security` — 4-B의 4와 같이 `[보안]` 접두로 `vNote`에 추가
5. 조건 `body('Approval_security')?['outcome']` = `Approve`
   - **아니요**: `vStatus` = rejected, `vReviewer` = 보안 응답자 메일. (이 분기에서 끝)
   - **예**:
     1. `Approval system` — 유형 **승인/거부 - 모든 사람의 승인 필요 (Everyone must approve)**, 할당 대상 `outputs('System_approvers')`, 제목 `... C등급 2/3 시스템 검토 ...`
        (ERP와 MES가 모두 있으면 두 사람 모두 승인해야 통과. 한 사람이면 그 사람만.)
     2. `Note system` — `[시스템]` 접두로 `vNote`에 추가
     3. 조건 `body('Approval_system')?['outcome']` = `Approve`
        - **아니요**: `vStatus` = rejected, `vReviewer` = 첫 반려자 메일
        - **예**:
          1. `Approval GBI` — 유형 **첫 번째 응답자**, 할당 대상 `owners`, 제목 `... C등급 3/3 GBI 승인 ...`
          2. `Note GBI` — `[GBI]` 접두로 `vNote`에 추가
          3. 조건 `outcome` = `Approve` → 예: `vStatus` = approved, `vGrade` = `C`, `vApproved` = `true`, `vReviewer` = GBI 응답자 / 아니요: `vStatus` = rejected, `vReviewer` = GBI 응답자

> "모든 사람의 승인 필요"는 한 사람이라도 거부하면 결과가 `Reject`가 된다.

## 5. 마무리 동작 (스위치 다음)

### 5-1. `Update body` — 작성

입력에 아래 JSON을 그대로 붙여 넣는다. **본문을 문자열로 쓰지 말고 이 작성 동작의 출력을 넘긴다.** 그래야 검토 의견에 따옴표나 줄바꿈이 있어도 JSON이 깨지지 않는다.

```json
{
  "formValues": [
    { "FieldName": "Status", "FieldValue": "@{variables('vStatus')}" },
    { "FieldName": "Grade", "FieldValue": "@{if(variables('vApproved'), variables('vGrade'), '')}" },
    { "FieldName": "ApprovedDate", "FieldValue": "@{if(variables('vApproved'), formatDateTime(convertFromUtc(utcNow(), 'Korea Standard Time'), 'yyyy-MM-dd'), '')}" },
    { "FieldName": "NextReviewDate", "FieldValue": "@{if(variables('vApproved'), formatDateTime(addToTime(convertFromUtc(utcNow(), 'Korea Standard Time'), outputs('Settings')?['recheckMonths'], 'Month'), 'yyyy-MM-dd'), '')}" },
    { "FieldName": "Reviewer", "FieldValue": "@{if(empty(variables('vReviewer')), '', concat('[{\"Key\":\"i:0#.f|membership|', variables('vReviewer'), '\"}]'))}" },
    { "FieldName": "ReviewNote", "FieldValue": "@{variables('vNote')}" }
  ],
  "bNewDocumentUpdate": false
}
```

- 날짜는 사이트 지역 설정 형식으로 넣는다. 한국어 사이트는 `yyyy-MM-dd`.
- 승인되지 않으면 확정 등급·승인일·다음 점검일은 비운다.

### 5-2. `Update item` — SharePoint에 HTTP 요청 보내기

3-6과 같고 **본문**에 동적 콘텐츠 `Update body`의 **출력(Outputs)** 하나만 넣는다.

### 5-3. `Check update` — 조건

`ValidateUpdateListItem`은 열 값이 잘못돼도 HTTP 200을 돌려준다. 결과를 확인한다.

- 조건: `length(body('Update_item')?['value'])` 가 0보다 큼 그리고
  `contains(string(body('Update_item')?['value']), '"HasException":true')` 이(가) `false`와 같음
- 아니요 → 메일 보내기 (V2): 받는 사람 `owners`, 제목 `[AX 앱 센터] F1 등록부 갱신 실패 #@{triggerOutputs()?['body/ID']}`, 본문에 `@{string(body('Update_item'))}` 와 항목 링크

### 5-4. `Notify developer` — 메일 보내기 (V2)

| 입력 | 값 |
|---|---|
| 받는 사람 | `@{body('Get_item')?['Developer']?['Email']};@{body('Get_item')?['OwnerManager']?['Email']}` |
| 제목 | 7장 문안 (결과별) — 식으로 고른다: `if(variables('vApproved'), '[AX 앱 센터] 등록 완료: ', '[AX 앱 센터] 등록 반려: ')` + 프로그램명 |
| 본문 | 승인/반려 문안 (조건 동작으로 두 메일을 나눠도 된다) |

## 6. 실행 설정

- `Approval*` 동작은 응답을 기다리는 동안 흐름이 멈춰 있다. 클라우드 흐름 한 번의 실행은 최대 30일이다. 30일 안에 응답이 없으면 실행이 끝나고 항목은 `검토 중`으로 남는다. F3이 기한이 지난 항목을 GBI팀에 알린다.
- 각 승인 동작의 **설정 → 시간 제한**은 비워 둔다(최대값).
- 흐름의 **설정 → 동시성 제어**는 끄고 둔다 (항목마다 따로 실행).

## 7. 메일·승인 문안

**승인 요청 세부 정보** (Markdown 사용 가능)

```
**프로그램명** @{body('Get_item')?['Title']}  (등록번호 @{triggerOutputs()?['body/ID']})
**자동 판정 등급** @{outputs('Grade')}
**법인 / 팀** @{body('Get_item')?['Entity']?['Value']} / @{body('Get_item')?['Dept']}
**만든 사람 / 책임 팀장** @{body('Get_item')?['Developer']?['DisplayName']} / @{body('Get_item')?['OwnerManager']?['DisplayName']}
**사용 범위** @{body('Get_item')?['UserScope']?['Value']}
**연결 시스템** @{join(body('Systems'), ', ')}
**실행 위치** @{body('Get_item')?['RunLocation']?['Value']}
**용도** @{body('Get_item')?['Purpose']}
**데이터 설명** @{body('Get_item')?['DataNote']}

반려할 때는 이유를 의견에 적어 주세요. 의견은 등록부의 검토 의견에 기록되어 전 직원이 볼 수 있습니다.
```

> `Systems`는 `Item link` 다음에 두는 **선택 (Select)** 동작이다. 보낸 사람(From) `body('Get_item')?['ConnectedSystems']`, 매핑은 텍스트 모드로 전환해 `item()?['Value']`.

**A등급 등록 완료 / 승인**

```
제목: [AX 앱 센터] 등록 완료: {프로그램명}

{만든 사람}님, 등록한 프로그램이 승인되었습니다.
- 등록번호: {ID}
- 확정 등급: {vGrade}
- 다음 점검일: {NextReviewDate}
- 등록부에서 보기: {Item link}

내용이 바뀌거나 사용을 멈출 때는 AX 앱 센터 홈의 '변경 신청하기'로 알려 주세요.

Your program has been approved and is now listed in the AX App Center catalog.
```

**반려**

```
제목: [AX 앱 센터] 등록 반려: {프로그램명}

{만든 사람}님, 등록한 프로그램이 반려되었습니다.
- 등록번호: {ID}
- 검토 의견: {vNote}
- 등록부에서 보기: {Item link}

의견을 반영해 다시 등록하거나 GBI팀에 문의해 주세요.

Your registration was not approved. See the review note above.
```

**B 참조 알림** (법인 AX 담당자)

```
제목: [AX 앱 센터] B등급 검토 시작 (참조): {프로그램명}

{법인}에서 등록한 프로그램이 B등급으로 판정되어 GBI팀 검토가 시작되었습니다. 참고용 알림이며 응답할 필요는 없습니다.
- 등록번호 / 팀 / 만든 사람: {ID} / {팀} / {만든 사람}
- 등록부에서 보기: {Item link}
```

## 8. (대안 사용 시) 보호 단계

`docs/manual-form.md` 1-5에서 **읽기 권한으로 양식 제출이 안 되어** `visitorsCanSubmit=true`로 바꾼 경우에만 만든다. 이때 직원은 본인 항목을 고칠 수 있으므로 등급·상태를 바꾸면 되돌린다.

별도 흐름 `AX F1b 보호`:

1. 트리거: SharePoint · **항목을 만들거나 수정한 경우 (When an item is created or modified)**, 등록부
2. 조건: 수정한 사람 메일 `triggerOutputs()?['body/Editor/Email']` 이(가) 공용 계정·GBI팀·검토자 목록(`Settings`에 `trusted` 배열로 둠)에 **없음** 그리고 `triggerOutputs()?['body/{VersionNumber}']` 이(가) `1.0`이 아님
3. SharePoint · **항목 또는 파일에 대한 변경 내용 가져오기(속성만) (Get changes for an item or a file (properties only))** — 이후(Since): 직전 버전 번호
4. 조건: `ColumnHasChanged`의 `Grade`, `Status`, `Reviewer`, `ReviewNote`, `ApprovedDate`, `NextReviewDate` 중 하나라도 `true`
5. 예: SharePoint에 HTTP 요청 보내기 GET `_api/web/GetList('<listPath>')/items(<ID>)/versions` → 직전 버전 값으로 5-1과 같은 `ValidateUpdateListItem` 수행 → GBI팀에 "보호 단계가 되돌림" 메일
6. 흐름 자신(공용 계정)의 수정은 2번 조건에서 걸러져 반복되지 않는다.

이 단계는 실제 테넌트에서 검증 후 `docs/verification-log.md`에 결과를 남긴다.

## 9. 테스트 (기획서 7.3)

| 제출 | 기대 |
|---|---|
| A (본인만, 모두 아니오) | 바로 `승인`, 확정 등급 A, 승인일 오늘, 다음 점검일 +12개월, 만든 사람·팀장에게 완료 메일 |
| B (팀 공용) | `검토 중` → GBI팀 전원에게 승인 요청, 법인 담당자에게 참조 메일 → 한 명이 승인하면 `승인`, 확정 등급 B |
| C (ERP 입력 예) | `검토 중` → 보안 → ERP 담당 → GBI 순서로 요청. 2단계에서 반려하면 3단계 요청 없이 `반려`, 검토 의견에 `[보안]`, `[시스템]` 기록 |
| C (ERP와 MES 모두) | 2단계 요청이 ERP·MES 담당 두 사람에게 가고 두 사람 모두 승인해야 3단계로 감 |
