# OpenAI 지원 문의 초안 — Compliance Logs Platform 대화 로그

> 아래 영문 본문을 그대로 복사해 admin.openai.com 의 지원(Support) 또는 담당 영업/CSM 에게 보내세요.
> **관리자 키는 절대 본문에 넣지 마세요.** 워크스페이스 ID 만으로 충분합니다.

## 무엇을 확인했는지 (문의 전 정리)

| 항목 | 결과 |
|---|---|
| 워크스페이스 | `f4fd05b9-c4ef-4fbf-8d31-e33dcdb44319` (ShinwonChatGPT) |
| 키 인증 | 정상 (`/logs` 200) |
| 쓸 수 있는 `event_type` | `AUDIT_LOG`, `AUTH_LOG`, `APP_LOG`, `APP_AUTH_LOG`, `CODEX_LOG`, `CODEX_SECURITY_LOG` |
| 대화 관련 이름 60개 시도 | 전부 `{"detail":"Invalid event_type ..."}` |
| `GET /conversations` | `410` — "migrate to the Compliance Logs Platform conversation logs" |
| `/conversations/logs` | `405`, `Allow: DELETE` (읽기 메서드 없음) |

즉 **안내는 "conversation logs 로 옮기라"고 하는데, 정작 그 conversation logs 를 읽을 방법이
이 워크스페이스에는 노출돼 있지 않습니다.**

---

## 영문 문의 본문

**Subject:** Compliance Logs Platform — how to retrieve conversation logs (workspace f4fd05b9-c4ef-4fbf-8d31-e33dcdb44319)

Hello,

We are building an internal compliance tool against the Compliance Logs Platform API
(`https://api.chatgpt.com/v1/compliance`) for our ChatGPT Enterprise workspace
`f4fd05b9-c4ef-4fbf-8d31-e33dcdb44319`. Our admin key authenticates successfully, but we
cannot find any way to retrieve **conversation logs**.

What we observe:

1. `GET /workspaces/{id}/logs?event_type=...&after=...` works and returns data for:
   `AUDIT_LOG`, `AUTH_LOG`, `APP_LOG`, `APP_AUTH_LOG`, `CODEX_LOG`, `CODEX_SECURITY_LOG`.

2. Every conversation-related `event_type` we tried is rejected, for example:
   ```
   GET /workspaces/{id}/logs?limit=1&event_type=CONVERSATION_LOG&after=2026-08-18T00:00:00Z
   400 {"detail":"Invalid event_type CONVERSATION_LOG"}
   ```
   We tried 60 variants (`CONVERSATION`, `CONVERSATION_LOG`, `CHAT_LOG`, `MESSAGE_LOG`,
   `CONTENT_LOG`, `TRANSCRIPT_LOG`, lower-case and CamelCase forms, …) — all rejected the same way.

3. `GET /workspaces/{id}/conversations` returns:
   ```
   410 {"detail":"The deprecated list conversations endpoint is no longer available for this
        workspace. Please migrate to the Compliance Logs Platform conversation logs."}
   ```

4. `/workspaces/{id}/conversations/logs` returns `405 Method Not Allowed` with `Allow: DELETE`,
   so there appears to be no read method on that path.

Our questions:

- **What is the exact `event_type` value (or endpoint) for conversation logs?**
- If conversation logging must be enabled for our workspace first, **what setting or entitlement
  do we need**, and can you enable it?
- Does the admin key need an additional scope beyond Compliance Logs read? (We see
  `400 Invalid event_type` rather than `403`, which suggests the value is not recognised at all
  rather than being permission-gated.)

Thank you.

---

## 함께 확인해 주실 것 (관리자 콘솔)

1. **admin.openai.com → 리소스 → 관리자 API 문서** 에서 Compliance Logs 의 `event_type` 목록 확인
2. **컴플라이언스/데이터 설정**에 대화 로깅(conversation logging) 활성화 항목이 있는지 확인
3. 관리자 키의 권한 목록에 대화 로그 관련 항목이 따로 있는지 확인
