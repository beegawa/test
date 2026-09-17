# ChatGPT 대화 로그 웹 콘솔

신원(Shinwon) ChatGPT Enterprise 워크스페이스의 **직원 대화 로그**를 불러와 조회·검색하고,
**로컬 DB 에 누적**해 30일 보관 기간이 지난 뒤에도 계속 볼 수 있게 하는 사내용 웹 프로그램입니다.

```
  관리자 키 1회 저장 ──▶ [기간 선택] ──▶ 수집 ──▶ SQLite 누적 ──▶ 검색 / 엑셀
        (OS 자격 증명)                    │            │
                                          │            └─ 중복은 자동으로 무시(id 기준)
                                          └─ 매일 자동 수집(collect.py)으로 30일 한계 극복
```

## 1. 시작하기

| 하고 싶은 것 | Windows | macOS / Linux |
|---|---|---|
| **대화만 받아 엑셀로** (가장 간단) | **`대화내용_받기.bat` 더블클릭** | `python3 export_conversations.py` |
| **매일 자동으로 쌓기** | **`자동수집_등록.bat` 더블클릭** | cron 등록 (4장 참고) |
| 웹 화면에서 검색·조회 | **`시작_Windows.bat` 더블클릭** | `python3 app.py` |

> 한글 파일명이 깨져 보이면 `GET_CHATS.bat` · `SETUP_AUTO.bat` 을 쓰세요 (내용 같음).

**처음 한 번만** `시작_Windows.bat` 으로 관리자 키를 저장하세요. 그다음부터는
`대화내용_받기.bat` 더블클릭만으로 끝납니다 — 받아서 엑셀을 만들고 바로 열어 줍니다.

| 환경 | 방법 |
|---|---|
| Windows | **`시작_Windows.bat` 더블클릭** — 패키지 설치 후 브라우저가 열립니다 |
| macOS | **`start_mac.command` 더블클릭** (또는 `bash start_mac.command`) |
| Linux | `pip install -r requirements.txt && python3 app.py` |

브라우저가 `http://127.0.0.1:5000` 으로 열립니다. **내 PC 에서만** 접속됩니다.

```bash
python3 app.py --port 8080      # 포트 변경
python3 app.py --no-open        # 브라우저 자동 열기 끄기
python3 app.py --db D:/logs.db  # DB 위치 지정
```

## 2. 화면 사용법

### ① 관리자 키 — 최초 1회만

관리자 콘솔(admin.openai.com) > 인증 정보 > 관리자 키에서 발급한 키를 붙여 넣고 [검증 후 저장].

- 저장 전에 실제 API 를 `limit=1` 로 한 번 호출해 **쓸 수 있는 키인지 확인**합니다.
  `401`(키 무효) 이나 `403`(권한 없음)이면 이유를 보여주고 **저장하지 않습니다.**
- 저장 위치는 **OS 자격 증명 저장소**(Windows 자격 증명 관리자 / macOS 키체인)입니다.
  자격 증명 저장소를 못 쓰는 환경이면 홈 폴더에 **소유자만 읽는 파일(0600)** 로 대신 저장합니다.
- 키는 코드·설정 파일·로그 어디에도 남지 않습니다. 필요하면 [키 삭제] 로 지웁니다.

> 키에는 **"규정 준수 로깅 플랫폼(Compliance Logs Platform)" 읽기 권한**이 있어야 합니다.

### ② 로그 가져오기

| 선택 | 의미 |
|---|---|
| 기간 1 / 7 / 30일 | 최근 N 일치를 받습니다. 30일이 API 보관 한계입니다 |
| 선택한 기간 전체 | 그 기간을 다시 훑습니다 (이미 있는 건 중복 저장되지 않음) |
| 마지막 수집 이후만 | 증분 수집 — 마지막으로 받은 지점부터 이어받습니다 |

수집은 백그라운드로 돌아가며 진행 상황(목록 / 다운로드 / 신규 저장 건수)이 실시간 표시됩니다.
오래 걸리면 [중지] 로 멈출 수 있고, 그때까지 받은 것은 그대로 남습니다.

### ③ 검색 · 엑셀

기간 · 사용자 · 키워드 · 이벤트 종류로 **DB 를 검색**합니다(이 단계에서는 API 를 부르지 않습니다).
표의 줄을 누르면 대화 전문과 원본 JSON 을 볼 수 있고, 화면에는 최대 500건까지 보여줍니다.
**전체 결과는 [엑셀 다운로드]** 로 받으세요 — 화면의 검색 조건이 그대로 적용됩니다.

## 2-1. 엑셀은 분석하기 좋게 나옵니다

`대화내용_받기.bat` 이 만드는 파일에는 시트가 넷 있습니다. 머리글에 필터가 걸려 있어
그대로 정렬·집계하실 수 있습니다.

| 시트 | 한 줄이 뜻하는 것 | 열 |
|---|---|---|
| **대화** | 메시지 하나 | 시간(한국) · 시간(UTC) · 이벤트 · 사용자 · 역할 · 대화 ID · 내용 |
| **대화별** | 대화 하나 | 시작 · 끝 · 사용자 · 메시지 수 · **첫 질문** · 대화 ID |
| **사용자별** | 사람 하나 | 사용자 · 메시지 수 · 대화 수 · 처음/마지막 사용 |
| **일자별** | 하루 | 날짜 · 메시지 수 · 대화 수 · 사용자 수 |

- 시각은 **한국 시간**을 앞에 둡니다 (UTC 도 함께 남깁니다).
- 원본 JSON 은 파일을 크게 만들어 **기본으로 빼 둡니다**. 필요하면 `--with-raw`.
- 아주 클 때는 `--csv` (엑셀에서 바로 열리도록 BOM 을 붙입니다).
- 100만 행이 넘으면 엑셀이 못 여니 `_1`, `_2` 로 나눠 저장합니다.

```bash
python3 export_conversations.py --csv              # CSV 로
python3 export_conversations.py --with-raw         # 원본 JSON 까지
python3 export_conversations.py --skip-pull        # 새로 받지 않고 DB 에서만
```

## 3. ⚠️ event_type 확인이 필요합니다

대화 내용에 해당하는 `event_type` 의 **정확한 이름은 관리자 콘솔의 "관리자 API 문서"**
(admin.openai.com → 리소스 → 관리자 API 문서)에서 확인해야 합니다. 공식 문서에서 확인된 건
로그인 기록 `AUTH_LOG` 하나뿐입니다.

그때까지는 후보를 `limit=1` 로 하나씩 시험 호출해 **정상 응답(200)하는 것만** 사용합니다.
결과는 DB 에 기억해 두고, [event_type 다시 탐지] 버튼으로 언제든 다시 확인할 수 있습니다.
하나도 통하지 않으면 **필터 없이 전체 이벤트**를 받습니다.

### 대화 메시지(`CONVERSATION_MESSAGE`)의 실제 구조

```json
{ "event_id": "...", "type": "CONVERSATION_MESSAGE",
  "actor":   { "user_id": "...", "user_email": "hong@example.com" },
  "timestamp": "2026-08-18T06:00:01.108000Z",
  "previous_message_id": "...",
  "message": { "id": "...",
               "author":  { "type": "user", "client_type": "windows_app" },
               "content": { "type": "text", "value": "실제 질문 내용" } },
  "conversation": { "id": "...", "title": "New chat", "is_pinned": false } }
```

주의할 점 — 처음에 이 세 가지를 틀렸습니다.

| 항목 | 있는 곳 | 흔한 실수 |
|---|---|---|
| 대화 본문 | `message.content.value` | `conversation` 을 내용으로 오인 → 제목·생성시각·`False` 가 표시됨 |
| 말한 사람 | `message.author.type` (`user`/`assistant`) | 없다고 보고 빈칸 처리 |
| 대화 id | **`conversation.id`** | 최상위 `conversation_id` 만 찾음 (다른 로그는 최상위에 있다) |

질문과 답변은 각각 별도 레코드로 오고, **`conversation.id` 가 같으면 같은 대화**입니다.
화면의 `대화 ID` 칸에 넣으면 한 대화를 순서대로 볼 수 있습니다.

### 지금까지 확인된 것 (2026-09, 실제 워크스페이스)

| 공식 분류 | event_type | 상태 |
|---|---|---|
| Audit | `AUDIT_LOG` | ✅ |
| Auth | `AUTH_LOG` | ✅ |
| App | `APP_LOG` | ✅ |
| App Auth | `APP_AUTH_LOG` | ✅ |
| Codex | `CODEX_LOG` | ✅ |
| Codex Security | `CODEX_SECURITY_LOG` | ✅ |
| **Conversation** | **`CONVERSATION_MESSAGE`** | 다른 종류와 달리 **뒤에 `_LOG` 가 붙지 않는다.** 관리자 콘솔의 키 권한 이름("대화 메시지: 읽기")과 짝이 맞는다 |

**대화 로그를 찾는 중에 나온 단서** (실제 응답):

```
[410] /conversations       "...no longer available for this workspace.
                            Please migrate to the Compliance Logs Platform conversation logs."
[405] /conversations/logs   Method Not Allowed   ← 경로는 존재한다. GET 이 아닐 뿐.
[400] /users                Invalid 'after' value ← 존재하지만 after 형식이 다르다
```

즉 대화 로그는 **이 워크스페이스에 분명히 있고**, 다만 `/logs?event_type=` 방식이 아닙니다.
`probe_conversations.py` 가 405 응답의 `Allow` 헤더를 읽어 어떤 메서드를 써야 하는지 알아냅니다.

대화 내용 로그만 이름을 못 찾았습니다. `explore_api.py` 로 API 스키마·다른 엔드포인트·
실제 로그 내용까지 훑어 계속 찾습니다.

```bash
python3 diagnose.py --key sk-admin-...        # 키 확인 + 이름 탐색 + 위치 탐색까지 한 번에
python3 diagnose.py --key sk-admin-... --quick  # 키 확인만 빠르게
python3 explore_api.py --key sk-admin-...     # 위치 탐색만 따로
```

**이름을 모를 때는 `sweep_event_types.py` 로 한 번에 훑습니다.** 그럴듯한 이름 49개를 시험해
응답으로 판별합니다.

```bash
python3 sweep_event_types.py --key sk-admin-...
python3 sweep_event_types.py --extra 시험할이름     # 이름을 직접 추가
```

| 응답 | 뜻 |
|---|---|
| `★ 정상` | 바로 쓸 수 있는 이름 |
| `없음` (`Invalid event_type`) | 그런 이름이 없음 |
| **`▲ 403` 등 다른 오류** | **이름은 맞는데 키에 그 권한이 없다는 뜻** — 가장 중요한 단서 |

**정확한 이름을 알아내는 가장 빠른 방법**은 서버에 직접 묻는 것입니다. `diagnose.py` 의 3단계가
일부러 없는 값을 보내서 API 가 돌려주는 허용 목록을 그대로 보여줍니다.

```
── 3. 서버에 허용되는 event_type 을 직접 물어보기 ──
  [422] {"detail":[{"msg":"Input should be 'CONVERSATION_LOG' or 'AUTH_LOG'", ...
```

알아낸 이름은 **코드를 고치지 않고** 환경변수로 바로 쓸 수 있습니다.

```bash
# Windows
set CHATGPT_EVENT_TYPES=알아낸이름,AUTH_LOG
py -3 app.py

# macOS / Linux
CHATGPT_EVENT_TYPES=알아낸이름,AUTH_LOG python3 app.py
```

특정 이름만 시험해 보려면:

```bash
python3 diagnose.py --event-type 시험할이름
```

확정되면 `settings.py` 의 `_DEFAULT_EVENT_TYPES` 맨 앞에 넣어 두세요.

## 3-1. 키 검증이 안 될 때 — 진단 도구

[검증 후 저장] 에서 막히면 `diagnose.py` 로 원인을 좁힙니다. 주소 조합을 하나씩 찔러보고
**서버가 보낸 설명을 그대로** 보여줍니다. 출력에 키는 찍히지 않습니다(앞 5자리/뒤 4자리만).

```bash
python3 diagnose.py --key sk-admin-...   # 키를 직접 넣어 시험 (저장하지 않음)
python3 diagnose.py                      # 이미 저장한 키로 시험
python3 diagnose.py --org org_...        # 조직 스코프도 함께 시험
```

| 결과 | 원인과 조치 |
|---|---|
| `401` | 일반 API 키(`sk-proj-…`)로는 안 됩니다. **관리자 콘솔 > 인증 정보 > 관리자 키**에서 발급한 키를 쓰세요 |
| `403` | 그 키에 **규정 준수 로깅 플랫폼 읽기 권한**이 없습니다 |
| `404` | 워크스페이스/조직 ID 가 틀렸습니다. `--workspace` / `--org` 로 바꿔 시험해 보세요 |
| `422` | 필수 파라미터(`event_type`, `after`)가 빠진 경우입니다. 프로그램 버그이니 알려주세요 |
| 연결 실패 | 회사 방화벽·프록시가 `api.chatgpt.com` 을 막고 있을 수 있습니다 |

> **API 는 `event_type` 과 `after` 를 필수로 요구합니다.** 둘 중 하나라도 빠지면 `422` 가 납니다.
> 그래서 키 검증도 후보 `event_type` 을 하나씩 넣어 보고 **하나라도 200 이면 통과**로 봅니다.

## 4. 과거 데이터 관리 — 매일 자동 수집

**API 는 30일치만 보관합니다.** 그 전에 받아 두지 않으면 영영 받을 수 없으므로,
`collect.py` 를 **하루 한 번** 돌리도록 걸어 두세요. 웹 콘솔에서 저장한 키를 그대로 씁니다.

**Windows 작업 스케줄러**
```
프로그램:  pythonw.exe
인수:      "C:\경로\chatgpt_log_console\collect.py" --days 2 --quiet
시작 위치: C:\경로\chatgpt_log_console
트리거:    매일 오전 3시 05분
```

**cron (Linux / macOS)**
```cron
5 3 * * * cd /경로/chatgpt_log_console && /usr/bin/python3 collect.py --days 2 --quiet
```

```bash
python3 export_conversations.py    # 대화만 받아 엑셀로 (바탕화면에 저장 후 열기)
python3 export_conversations.py --days 7 --user hong@shinwon.com
python3 export_conversations.py --skip-pull --q 매출   # 새로 받지 않고 DB 에서만
python3 collect.py                 # 증분 수집 (기본)
python3 collect.py --full --days 7 # 최근 7일을 다시 훑기
python3 collect.py --json          # 결과를 JSON 으로 출력 (모니터링용)
```

종료 코드: `0` 정상 · `1` 일부 오류 · `2` 키 없음/설정 오류. 실행 로그는 데이터 폴더의 `collect.log`.

## 5. 저장되는 것

| 파일 | 위치 (기본) | 내용 |
|---|---|---|
| `chatgpt_logs.db` | `~/.chatgpt_log_console/` (0600) | 누적된 로그 |
| `admin_key.json` | 같은 폴더 (0600) | 자격 증명 저장소를 못 쓸 때만 |
| `collect.log` | 같은 폴더 | 자동 수집 실행 기록 |

`CHATGPT_LOG_DATA_DIR` 환경변수로 폴더를 바꿀 수 있습니다.

```sql
CREATE TABLE logs(
    id            TEXT PRIMARY KEY,  -- 로그 고유 id (중복 방지, 실제로는 event_id)
    event_type    TEXT,              -- 로그 종류 (요청한 event_type)
    ts            TEXT,              -- 이벤트 시각 (ISO 8601, UTC)
    user          TEXT,              -- 사용자 (actor.user_email)
    action        TEXT,              -- 무슨 일이 있었는지 (CONVERSATION_DELETE 등)
    conversation_id TEXT,            -- 관련 대화 id (있는 로그만)
    content       TEXT,              -- 검색용 평문 (원본에서 뽑아낸 대화 내용)
    summary       TEXT,              -- 표에 보여줄 한 줄 요약
    source_log_id TEXT,              -- 내려받은 로그 파일 id
    raw           TEXT,              -- 원본 JSON 전체
    fetched_at    TEXT               -- 우리가 받은 시각
);
```

원본 JSON 은 **통째로 보관**합니다. 필드 이름이 달라 `user`·`ts` 를 못 읽었더라도 원본은 남으므로,
`records.py` 의 후보 키만 늘려 다시 해석할 수 있습니다.

## 6. API 엔드포인트

| 메서드 | 경로 | 기능 |
|---|---|---|
| GET | `/api/status` | 키 저장 여부·워크스페이스·누적 통계·수집 상태 |
| POST | `/api/save-key` | 키를 **검증한 뒤** 저장 |
| POST | `/api/forget-key` | 키 삭제 |
| POST | `/api/detect-event-types` | event_type 후보 재탐지 |
| POST | `/api/pull` | 수집 시작 (백그라운드, `202`) |
| GET | `/api/pull/status` | 진행률·결과·미리보기 |
| POST | `/api/pull/cancel` | 수집 중지 |
| GET | `/api/search` | DB 검색 (`from` `to` `user` `q` `event_type`) |
| GET | `/api/log/<id>` | 한 건의 전문과 원본 JSON |
| GET | `/api/users` | 사용자 목록 |
| GET | `/api/download.xlsx` | 엑셀 — 조건을 주면 그대로, 없으면 마지막 검색 결과 |

## 7. 파일 구성

| 파일 | 역할 |
|---|---|
| `app.py` | Flask 웹 서버 · 엔드포인트 · 백그라운드 수집 작업 |
| `static/index.html` | 화면 (프레임워크 없는 단일 HTML, 다크모드) |
| `collect.py` | 스케줄러용 헤드리스 증분 수집 |
| `collector.py` | 수집 절차 (웹·스케줄러가 공유) |
| `compliance.py` | Compliance API 클라이언트 (페이지네이션 · 재시도 · 오류 구분) |
| `store.py` | SQLite 누적 저장·검색 |
| `records.py` | 원본 JSON → 표/DB 행 변환 |
| `keystore.py` | 관리자 키 보관 |
| `xlsx_export.py` | 엑셀 내보내기 |
| `settings.py` | 설정값 (워크스페이스 ID, event_type 후보 등) |

## 8. 보안 · 컴플라이언스 (먼저 확인하세요)

- 결과에는 **직원의 실제 대화 내용(개인정보 포함 가능)** 이 담깁니다.
  개인정보보호법상 **근로자 모니터링 고지·동의, 목적 제한, 접근 권한 최소화**를 먼저 확인하세요.
- 기본값은 `127.0.0.1` 바인딩이라 **외부에서 접속되지 않습니다.**
  사내 서버에 올린다면 **사내 인증(SSO/베이식) + HTTPS + 접근 로그**를 반드시 앞에 두세요.
  (`--host` 로 바인딩을 열면 프로그램이 경고를 남깁니다.)
- DB·엑셀 파일은 접근 통제된 위치에 두고, 가능하면 디스크 암호화를 켜세요.
- 관리자 키는 **최소 권한(규정 준수 로깅 읽기)** 만, 만료일 설정을 권장합니다.

## 9. 테스트

```bash
python3 -m pytest              # 이 폴더에서
```

단위 테스트(키 보관·정규화·DB·페이지네이션·재시도)와 함께, **로컬 HTTP 서버로 Compliance API 를
흉내 내 "키 저장 → 수집 → 검색 → 엑셀" 전 과정을 실제 통신으로 돌리는 통합 테스트**가 있습니다.

## 10. 기획서 대비 구현 메모

| 항목 | 기획서 | 구현 | 이유 |
|---|---|---|---|
| `/api/pull` | 동기 호출로 미리보기 반환 | 백그라운드 + `/api/pull/status` 폴링 | 30일 수집은 몇 분씩 걸려 브라우저가 멈춥니다 |
| UI | `app.py` 에 HTML 내장 | `static/index.html` 분리 | 내용은 동일한 단일 HTML, 수정이 쉽습니다 |
| 엑셀 | pandas + openpyxl | openpyxl 만 | 표 하나를 쓰는 데 pandas 는 불필요합니다 |
| DB 스키마 | id·event_type·ts·user·raw | + `content`·`summary`·`source_log_id`·`fetched_at` | 키워드 검색과 증분 수집에 필요합니다 |
| DB 위치 | 프로그램 폴더 | `~/.chatgpt_log_console/` (0600) | 대화 내용이 저장소에 딸려 들어가는 사고를 막습니다 |

**아직 확정되지 않은 것**: 대화 로그의 정확한 `event_type` 이름(3장)과, 실제 응답의 필드 이름입니다.
후자는 원본 JSON 을 통째로 보관하고 후보 키로 해석하는 방식이라, 실제 데이터를 한 번 받아 본 뒤
`records.py` 의 후보 목록만 손보면 됩니다.
