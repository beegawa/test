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
