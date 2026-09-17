"""실제 Compliance API 응답 구조로 정규화가 되는지.

아래 레코드는 실제 워크스페이스 응답에서 가져온 모양이다(이메일·IP·id 는 가명).
처음 만들 때는 구조를 추측해서 짰다가, 실제 응답을 보고 고친 부분이라
회귀가 나기 쉬운 곳이다.
"""

from records import describe, extract_action, extract_conversation_id, normalize

AUDIT = {
    "event_id": "268a5b96-6412-4979-ad81-ce49fbb8f0c6",
    "type": "AUDIT_LOG",
    "principal": {"id": "f4fd05b9", "type": "CHATGPT_WORKSPACE"},
    "actor": {"type": "ACCOUNT_USER", "user_id": "user-kPXa", "user_email": "aaa@example.com"},
    "timestamp": "2026-08-18T05:43:28.095317Z",
    "action_result": "SUCCESS",
    "action_privilege": "STANDARD_USER",
    "request_metadata": {"client_ip": "1.2.3.4", "client_ip_details": {"country": "KR"}},
    "action_data": {"conversation_id": "6a83e8b7-57e8-8341"},
    "action": "CONVERSATION_DELETE",
}
AUTH = {
    "event_id": "6060ca3a", "type": "AUTH_LOG",
    "actor": {"type": "ACCOUNT_USER", "user_id": "user-zxvi", "user_email": "bbb@example.com"},
    "timestamp": "2026-08-18T08:36:52Z",
    "request_metadata": {"client_ip": "10.224.5.25"},
    "action_data": {"action": "logout_success", "role": "standard-user"},
}
APP = {
    "event_id": "561769e7", "type": "APP_LOG",
    "actor": {"type": "ACCOUNT_USER", "user_id": "user-Ion7", "user_email": "ccc@example.com"},
    "timestamp": "2026-08-18T05:22:28.699494Z",
    "app_id": "connector_4aaa", "app_name": "Microsoft Outlook Email", "app_type": "SERVICE",
    "conversation_id": "20d14a2c-211f-4cc1", "log_type": "request",
    "input": {"top": 30, "order_by": "receivedDateTime desc", "_meta": {"timezone": "Asia/Seoul"}},
}
CODEX = {
    "event_id": "a491cff4", "type": "CODEX_LOG",
    "actor": {"type": "ACCOUNT_USER", "user_id": "user-cJEK", "user_email": "ddd@example.com"},
    "timestamp": "2026-08-18T06:08:12.697931Z",
    "event_type": "PROMPT_SENT", "client_id": "CODEX_WORK_DESKTOP",
    "event_details": {"detail_type": "PROMPT_SENT", "session_id": "01a0", "model": "gpt-5.6-luna",
                      "prompt_text": "이 함수 리팩터링 해줘"},
}


def 정규화(raw):
    return normalize(raw, log_id="eclf_x", event_type_hint=raw["type"])


def test_id_는_event_id_를_쓴다():
    # 최상위에 id 가 없고 principal.id 가 있어서, 잘못 잡으면 모든 행이 같은 id 가 된다
    assert 정규화(AUDIT)["id"] == "268a5b96-6412-4979-ad81-ce49fbb8f0c6"
    assert 정규화(AUTH)["id"] != 정규화(AUDIT)["id"]


def test_사용자는_actor_안의_이메일에서_꺼낸다():
    assert 정규화(AUDIT)["user"] == "aaa@example.com"
    assert 정규화(APP)["user"] == "ccc@example.com"


def test_로그_종류는_요청한_값을_쓴다():
    # CODEX_LOG 레코드 안의 event_type 은 세부 동작(PROMPT_SENT)이라 종류가 아니다
    assert 정규화(CODEX)["event_type"] == "CODEX_LOG"
    assert 정규화(CODEX)["action"] == "PROMPT_SENT"


def test_감사_인증_로그의_요약이_비지_않는다():
    # 이 로그들은 '내용' 이 없다. 그래도 무슨 일이 있었는지는 보여야 한다.
    assert 정규화(AUDIT)["summary"] == "CONVERSATION_DELETE"
    assert "logout_success" in 정규화(AUTH)["summary"]


def test_앱_로그는_요청_파라미터를_내용으로_오인하지_않는다():
    요약 = 정규화(APP)["summary"]
    assert "Microsoft Outlook Email" in 요약
    assert "receivedDateTime" not in 요약      # top/order_by/_meta 는 잡음이다


def test_codex_의_prompt_text_를_내용으로_담는다():
    결과 = 정규화(CODEX)
    assert "이 함수 리팩터링 해줘" in 결과["content"]
    assert "gpt-5.6-luna" in 결과["summary"]


def test_대화_id_는_어디에_있든_찾아낸다():
    assert 정규화(AUDIT)["conversation_id"] == "6a83e8b7-57e8-8341"   # action_data 안
    assert 정규화(APP)["conversation_id"] == "20d14a2c-211f-4cc1"      # 최상위
    assert 정규화(AUTH)["conversation_id"] == ""                       # 없으면 빈 값


def test_시각은_마이크로초까지_와도_읽는다():
    assert 정규화(AUDIT)["ts"] == "2026-08-18T05:43:28Z"
    assert 정규화(AUTH)["ts"] == "2026-08-18T08:36:52Z"


def test_동작과_대화id_를_따로_꺼내는_함수():
    assert extract_action(AUTH) == "logout_success"
    assert extract_conversation_id(APP) == "20d14a2c-211f-4cc1"
    assert describe({"action": "X"}, "") == "X"


def test_원본은_통째로_보관된다():
    assert 정규화(AUDIT)["raw"] is AUDIT


# ── CONVERSATION_MESSAGE : 실제 구조 (본문만 예시 문장으로 대체) ──────────
CONV = {
    "event_id": "9c27bc29-a5c9-48e4-b217-0d9e3fcbbd74",
    "type": "CONVERSATION_MESSAGE",
    "principal": {"id": "f4fd05b9", "type": "CHATGPT_WORKSPACE"},
    "actor": {"type": "ACCOUNT_USER", "user_id": "user-rmE1", "user_email": "eee@example.com"},
    "timestamp": "2026-08-18T06:00:01.108000Z",
    "previous_message_id": "4aaf0c62",
    "message": {
        "id": "22a35076", "created_at": "2026-08-18T06:00:01.108000Z",
        "author": {"type": "user", "client_type": "windows_app"},
        "content": {"type": "text", "value": "회계 처리 방법을 알려줘"},
    },
    "conversation": {"id": "6a83f4cc-78fc-8343", "title": "New chat",
                     "created_at": "2026-08-18T05:59:41.924513Z",
                     "is_pinned": False, "is_temporary_chat": False},
}


def 대화(**바꿀것):
    raw = {**CONV, **바꿀것}
    return normalize(raw, log_id="eclf_x", event_type_hint="CONVERSATION_MESSAGE")


def test_대화_본문은_message_content_value_에서_꺼낸다():
    결과 = 대화()
    assert "회계 처리 방법을 알려줘" in 결과["content"]
    # conversation 은 메타데이터다. 제목·생성시각·False 가 내용에 섞이면 안 된다.
    assert "New chat" not in 결과["content"]
    assert "False" not in 결과["content"]
    assert "2026-08-18T05:59:41" not in 결과["content"]


def test_말한_사람이_사용자인지_ChatGPT_인지_구분한다():
    assert 대화()["action"] == "사용자"
    답변 = 대화(message={**CONV["message"], "author": {"type": "assistant"}})
    assert 답변["action"] == "ChatGPT"
    assert 답변["summary"].startswith("ChatGPT: ")


def test_대화_id_는_conversation_id_에_들어_있다():
    # 최상위에 conversation_id 가 없고 conversation.id 에 있다
    assert 대화()["conversation_id"] == "6a83f4cc-78fc-8343"


def test_제목이_있으면_요약_앞에_붙이고_New_chat_은_생략한다():
    assert 대화()["summary"] == "사용자: 회계 처리 방법을 알려줘"
    이름있음 = 대화(conversation={"id": "c1", "title": "회계 문의"})
    assert 이름있음["summary"].startswith("[회계 문의] ")


def test_같은_대화의_질문과_답변이_대화id_로_묶인다():
    질문 = 대화()
    답변 = 대화(event_id="9c27bc30",
               message={"id": "m2", "author": {"type": "assistant"},
                        "content": {"type": "text", "value": "가능합니다."}})
    assert 질문["conversation_id"] == 답변["conversation_id"]
    assert 질문["id"] != 답변["id"]


def test_앱로그의_검색어는_내용으로_살리고_페이지_파라미터는_버린다():
    raw = {**APP, "input": {"query": "received>=2026-08-15 read:false",
                            "from_index": 0, "size": 40, "_meta": {"timezone": "Asia/Seoul"}}}
    요약 = normalize(raw, log_id="eclf_x", event_type_hint="APP_LOG")["summary"]
    assert "received>=2026-08-15" in 요약      # 무엇을 찾았는지는 남기고
    assert "from_index" not in 요약            # 페이지 파라미터는 버린다
    assert "Asia/Seoul" not in 요약
