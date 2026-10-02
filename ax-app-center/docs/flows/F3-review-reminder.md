# F3 정기 점검 알림

매주 월요일 아침, 점검 기한이 다가온 승인 항목의 만든 사람·책임 팀장에게 점검 요청을 보내고, 검토가 기한을 넘긴 항목을 GBI팀에 알린다. (기획서 5.8)

- 종류: 예약된 클라우드 흐름 (Scheduled cloud flow)
- 이름: `AX F3 정기 점검 알림`
- 커넥터: SharePoint, Office 365 Outlook — 표준
- 소유자: 공용 계정(D7), GBI팀 공동 소유
- 소요 시간: 약 15분

## 1. 트리거

| 설정 | 값 |
|---|---|
| 트리거 | **되풀이 (Recurrence)** |
| 간격 / 빈도 | `1` / `주 (Week)` |
| 표준 시간대 | `(UTC+09:00) 서울` |
| 요일 | `월요일` |
| 시간 / 분 | `8` / `30` |

## 2. 동작

### 2-1. `Settings` — 작성

```json
{
  "siteUrl": "https://<tenant>.sharepoint.com/sites/ax-app-center",
  "owners": "<GBI팀1@회사>;<GBI팀2@회사>",
  "reminderDaysBefore": 30,
  "slaCalendarDays": 7,
  "labels": { "approved": "승인 / Approved", "inReview": "검토 중 / In review" }
}
```

- `reminderDaysBefore`: `config.json`의 `review.reminderDaysBefore`.
- `slaCalendarDays`: `review.slaBusinessDays`(N)를 월요일 기준 달력 일수로 바꾼 값 = `N + 2 × 올림(N ÷ 5)`. N=5 → 7, N=3 → 5, N=10 → 14. 공휴일은 따지지 않는다.

### 2-2. `Due items` — SharePoint · 항목 가져오기 (Get items)

| 입력 | 값 |
|---|---|
| 목록 이름 | `프로그램 등록부` |
| 필터 쿼리 | `Status eq '@{outputs('Settings')?['labels']?['approved']}' and NextReviewDate le '@{formatDateTime(addDays(convertFromUtc(utcNow(), 'Korea Standard Time'), outputs('Settings')?['reminderDaysBefore']), 'yyyy-MM-dd')}'` |
| 정렬 기준 | `NextReviewDate` |
| 상위 개수 | `500` |

다음 점검일이 이미 지난 항목도 함께 잡힌다 (`점검 예정` 보기와 같은 기준).

### 2-3. `Each due` — 각각에 적용 `body('Due_items')?['value']`

안에 Office 365 Outlook · **메일 보내기 (V2)**:

| 입력 | 값 |
|---|---|
| 받는 사람 | `@{items('Each_due')?['Developer']?['Email']};@{items('Each_due')?['OwnerManager']?['Email']}` |
| 제목 | `[AX 앱 센터] 정기 점검 요청: @{items('Each_due')?['Title']} (다음 점검일 @{formatDateTime(items('Each_due')?['NextReviewDate'], 'yyyy-MM-dd')})` |
| 본문 | 아래 |

```
@{items('Each_due')?['Developer']?['DisplayName']}님,

등록한 프로그램의 정기 점검 시기가 되었습니다.
- 프로그램: @{items('Each_due')?['Title']} (등록번호 @{items('Each_due')?['ID']})
- 다음 점검일: @{formatDateTime(items('Each_due')?['NextReviewDate'], 'yyyy-MM-dd')}

아래를 확인해 주세요.
1. 지금도 쓰고 있나요? 쓰지 않으면 '변경 신청하기'에서 '사용 중단' 또는 '폐기'를 신청해 주세요.
2. 사용 범위, 다루는 데이터, 연결 시스템이 바뀌었나요? 바뀌었으면 '변경 신청하기'에서 '등급 재판정'을 신청해 주세요.
3. 바뀐 것이 없으면 이 메일에 "변경 없음"이라고 회신해 주세요. GBI팀이 다음 점검일을 갱신합니다.

등록부에서 보기: @{outputs('Settings')?['siteUrl']}/Lists/AppRegistry/DispForm.aspx?ID=@{items('Each_due')?['ID']}

It is time for the periodic review of your program. Reply "no change" or submit a change request.
```

- 메일의 **회신 주소(Reply To)** 는 `outputs('Settings')?['owners']` 로 둔다 (고급 옵션).

### 2-4. `Overdue reviews` — 항목 가져오기

| 입력 | 값 |
|---|---|
| 목록 이름 | `프로그램 등록부` |
| 필터 쿼리 | `Status eq '@{outputs('Settings')?['labels']?['inReview']}' and Created le '@{formatDateTime(addDays(utcNow(), mul(-1, outputs('Settings')?['slaCalendarDays'])), 'yyyy-MM-ddTHH:mm:ssZ')}'` |
| 정렬 기준 | `Created` |

F1이 등록 직후 `검토 중`으로 바꾸므로 등록일(Created)을 검토 시작일로 본다.

### 2-5. `Has overdue` — 조건

`length(body('Overdue_reviews')?['value'])` 가 `0`보다 큼

- 예:
  1. **HTML 표 만들기 (Create HTML table)** — 보낸 사람 `body('Overdue_reviews')?['value']`, 열: 사용자 지정
     | 머리글 | 값 |
     |---|---|
     | 등록번호 | `item()?['ID']` |
     | 프로그램명 | `item()?['Title']` |
     | 법인 | `item()?['Entity']?['Value']` |
     | 자동 판정 등급 | `item()?['AutoGrade']` |
     | 등록일 | `formatDateTime(item()?['Created'], 'yyyy-MM-dd')` |
  2. **메일 보내기 (V2)** — 받는 사람 `owners`, 제목 `[AX 앱 센터] 검토 기한 초과 @{length(body('Overdue_reviews')?['value'])}건`, 본문:

```
검토 중 상태로 @{outputs('Settings')?['slaCalendarDays']}일(약 @{div(mul(outputs('Settings')?['slaCalendarDays'], 5), 7)}영업일)이 지난 항목입니다.
승인 요청이 30일을 넘기면 흐름 F1의 대기가 끝나므로, 그 전에 처리하거나 등록부에서 직접 상태를 바꿔 주세요.

@{body('Create_HTML_table')}

검토 대기 보기: @{outputs('Settings')?['siteUrl']}/Lists/AppRegistry/ReviewQueue.aspx
```

## 3. 테스트

1. 테스트 사이트에서 승인 항목 하나의 `다음 점검일`을 오늘+10일로 바꾼다 (GBI팀 계정).
2. 다른 항목 하나를 `검토 중`으로 두고 (등록일이 8일 이상 지난 항목이 없으면 `slaCalendarDays`를 잠시 `0`으로).
3. 흐름 편집 화면에서 **테스트 → 수동**으로 실행한다.
4. 1의 만든 사람·팀장에게 점검 요청 메일, GBI팀에 기한 초과 메일이 오는지 본다. 끝나면 `slaCalendarDays`를 되돌린다.
