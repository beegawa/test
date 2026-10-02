# F2 변경 신청 알림

변경 신청 목록에 새 항목이 생기면 GBI팀 메일과 Teams 채널에 알린다. (기획서 5.8)

- 종류: 자동화된 클라우드 흐름
- 이름: `AX F2 변경 신청 알림`
- 커넥터: SharePoint, Office 365 Outlook, Microsoft Teams — 모두 표준
- 소유자: 공용 계정(D7), GBI팀 공동 소유
- 소요 시간: 약 10분

> 알림만 한다. 등록부 수정은 GBI팀이 직접 하고, 변경 신청 항목의 `처리 상태`·`처리자`·`처리 의견`을 채운다 (`docs/admin-guide.md` 3장).

## 1. 트리거

| 설정 | 값 |
|---|---|
| 트리거 | SharePoint · **항목을 만든 경우 (When an item is created)** |
| 사이트 주소 | `https://<tenant>.sharepoint.com/sites/ax-app-center` |
| 목록 이름 | `변경 신청` |

## 2. 동작

### 2-1. `Settings` — 작성

```json
{
  "siteUrl": "https://<tenant>.sharepoint.com/sites/ax-app-center",
  "owners": "<GBI팀1@회사>;<GBI팀2@회사>"
}
```

### 2-2. `Get app` — SharePoint · 항목 가져오기

| 입력 | 값 |
|---|---|
| 목록 이름 | `프로그램 등록부` |
| ID | 식 `int(triggerOutputs()?['body/AppRegNo'])` |

등록번호가 잘못되어 항목이 없으면 이 동작이 실패한다. 다음 동작에서 처리한다.

### 2-3. `App info` — 작성

이 동작의 **설정 → 실행 후 구성 (Configure run after)** 에서 `성공`, `실패` 모두 체크한다.

```
if(equals(actions('Get_app')?['status'], 'Succeeded'),
   concat(body('Get_app')?['Title'], ' (', body('Get_app')?['Entity']?['Value'], ' / ', body('Get_app')?['Dept'], ', 상태: ', body('Get_app')?['Status']?['Value'], ')'),
   '⚠ 등록부에 없는 등록번호입니다. 신청자에게 확인이 필요합니다.')
```

### 2-4. `Links` — 작성

```json
{
  "request": "@{outputs('Settings')?['siteUrl']}/Lists/ChangeRequests/DispForm.aspx?ID=@{triggerOutputs()?['body/ID']}",
  "app": "@{outputs('Settings')?['siteUrl']}/Lists/AppRegistry/DispForm.aspx?ID=@{triggerOutputs()?['body/AppRegNo']}"
}
```

### 2-5. `Mail GBI` — Office 365 Outlook · 메일 보내기 (V2)

| 입력 | 값 |
|---|---|
| 받는 사람 | `outputs('Settings')?['owners']` |
| 제목 | `[AX 앱 센터] 변경 신청 #@{triggerOutputs()?['body/ID']}: @{triggerOutputs()?['body/RequestType/Value']} - 등록번호 @{triggerOutputs()?['body/AppRegNo']}` |
| 본문 | 아래 |

```
변경 신청이 접수되었습니다.

- 요청 제목: @{triggerOutputs()?['body/Title']}
- 유형: @{triggerOutputs()?['body/RequestType/Value']}
- 등록번호: @{triggerOutputs()?['body/AppRegNo']}  @{outputs('App_info')}
- 신청자: @{triggerOutputs()?['body/Author/DisplayName']} (@{triggerOutputs()?['body/Author/Email']})
- 변경 내용:
@{triggerOutputs()?['body/Detail']}

신청 보기: @{outputs('Links')?['request']}
등록부 항목: @{outputs('Links')?['app']}

처리 후 변경 신청 항목의 '처리 상태', '처리자', '처리 의견'을 채워 주세요.
```

### 2-6. `Post Teams` — Microsoft Teams · **채팅 또는 채널에서 메시지 게시 (Post message in a chat or channel)**

| 입력 | 값 |
|---|---|
| 게시자 | 흐름 봇 (Flow bot) |
| 게시 위치 | 채널 (Channel) |
| 팀 / 채널 | GBI팀이 정한 팀과 채널 (D11, 아직 미정) |
| 메시지 | 아래 |

```
<b>[AX 앱 센터] 변경 신청 #@{triggerOutputs()?['body/ID']}</b><br>
유형: @{triggerOutputs()?['body/RequestType/Value']} · 등록번호 @{triggerOutputs()?['body/AppRegNo']} @{outputs('App_info')}<br>
@{triggerOutputs()?['body/Title']}<br>
<a href="@{outputs('Links')?['request']}">신청 보기</a>
```

`Mail GBI`와 `Post Teams`는 둘 다 `App info` 다음에 병렬로 두어도 된다. 한쪽이 실패해도 다른 쪽이 가도록 `Post Teams`의 실행 후 구성에 `실패`도 체크한다.

## 3. 테스트

| 제출 | 기대 |
|---|---|
| 존재하는 등록번호로 정보 변경 신청 | GBI팀 메일과 Teams 채널에 프로그램명이 붙은 알림 |
| 없는 등록번호(예: 99999) | 알림은 가고 `⚠ 등록부에 없는 등록번호` 문구가 붙음. 흐름 실행은 성공으로 끝남 |
