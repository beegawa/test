"""Compliance API 클라이언트 - 페이지네이션·재시도·오류 처리."""

import pytest
from conftest import FakeResponse, jsonl

from compliance import AuthError, ComplianceClient, ComplianceError, ForbiddenError, RateLimitError


def test_워크스페이스_스코프_경로와_인증_헤더(client, session):
    session.pages = [{"data": [], "has_more": False}]
    client.validate()
    call = session.calls[0]
    assert call["url"] == "https://example.test/v1/compliance/workspaces/ws_1/logs"
    assert call["headers"]["Authorization"] == "Bearer sk-test-key"
    # event_type 과 after 는 이 API 의 필수 파라미터다 (빠지면 422)
    assert call["params"]["limit"] == 1
    assert call["params"]["event_type"]
    assert call["params"]["after"].endswith("Z")


def test_조직_ID_가_있으면_조직_스코프를_쓴다(session):
    client = ComplianceClient("k", base_url="https://e.test", org_id="org_9", session=session,
                              sleep=lambda _s: None)
    assert client.scope_path == "/organizations/org_9"
    assert client.scope_label == "organization:org_9"


def test_401_은_키_무효_403_은_권한_없음으로_구분한다(client, session):
    session.status_queue = [401]
    with pytest.raises(AuthError):
        client.validate()
    session.status_queue = [403]
    with pytest.raises(ForbiddenError):
        client.validate()


def test_429_는_지수_백오프로_재시도하고_결국_성공한다(client, session):
    session.status_queue = [429, 429]
    session.pages = [{"data": [{"id": "log_1"}], "has_more": False}]
    assert client.validate()["ok"] is True
    assert len(session.calls) == 3


def test_재시도를_다_쓰면_RateLimitError(client, session):
    session.status_queue = [429] * client.max_retries
    with pytest.raises(RateLimitError):
        client.validate()


def test_5xx_도_재시도한다(client, session):
    session.status_queue = [500, 503]
    session.pages = [{"data": [], "has_more": False}]
    assert client.validate()["ok"] is True


def test_has_more_면_last_end_time_을_after_로_넣어_이어받는다(client, session):
    session.pages = [
        {"data": [{"id": "log_1"}, {"id": "log_2"}], "has_more": True,
         "last_end_time": "2026-09-16T00:00:00Z"},
        {"data": [{"id": "log_3"}], "has_more": False, "last_end_time": "2026-09-17T00:00:00Z"},
    ]
    ids = [log_id for log_id, _cursor in client.iter_log_ids(event_type="CONVERSATION_LOG")]
    assert ids == ["log_1", "log_2", "log_3"]
    assert session.calls[1]["params"]["after"] == "2026-09-16T00:00:00Z"
    assert session.calls[1]["params"]["event_type"] == "CONVERSATION_LOG"


def test_커서가_제자리면_무한루프하지_않고_멈춘다(client, session):
    같은페이지 = {"data": [{"id": "log_1"}], "has_more": True, "last_end_time": "2026-09-16T00:00:00Z"}
    session.pages = [dict(같은페이지) for _ in range(10)]
    ids = [log_id for log_id, _ in client.iter_log_ids()]
    assert ids == ["log_1", "log_1"]        # 두 번째에서 커서가 안 나아간 걸 알아채고 중단


def test_max_items_로_수집량을_제한한다(client, session):
    session.pages = [{"data": [{"id": f"log_{i}"} for i in range(10)], "has_more": True,
                      "last_end_time": "2026-09-16T00:00:00Z"}]
    assert len(list(client.iter_log_ids(max_items=3))) == 3


def test_개별_로그는_JSONL_로_파싱한다(client, session):
    session.logs["log_1"] = jsonl({"id": "a"}, {"id": "b"}) + "\n\n"
    assert client.fetch_log("log_1") == [{"id": "a"}, {"id": "b"}]


def test_깨진_줄은_건너뛰고_나머지를_살린다(client, session):
    session.logs["log_1"] = '{"id": "a"}\n{깨진 줄\n{"id": "b"}'
    assert client.fetch_log("log_1") == [{"id": "a"}, {"id": "b"}]


def test_없는_로그는_ComplianceError(client, session):
    with pytest.raises(ComplianceError):
        client.fetch_log("없음")


def test_event_type_후보를_시험해_통하는_것만_고른다(client, session):
    session.event_types_ok = {"CONVERSATION_LOG", "AUTH_LOG"}
    usable = client.detect_event_types(["MESSAGE_LOG", "CONVERSATION_LOG", "없는타입", "AUTH_LOG"])
    assert usable == ["CONVERSATION_LOG", "AUTH_LOG"]


def test_탐지_중_401_은_삼키지_않고_올린다(client, session):
    session.status_queue = [401]
    with pytest.raises(AuthError):
        client.detect_event_types(["CONVERSATION_LOG"])


def test_빈_키는_생성_단계에서_거절한다(session):
    with pytest.raises(AuthError):
        ComplianceClient("   ", session=session)


def test_연결_실패는_재시도_후_ComplianceError(client, session):
    import requests

    def boom(*_a, **_k):
        raise requests.RequestException("네트워크 끊김")

    session.get = boom
    with pytest.raises(ComplianceError):
        client.validate()


def test_JSON_이_아닌_응답은_오류로_본다(client, session):
    session.get = lambda *a, **k: FakeResponse(200, text="<html>")
    with pytest.raises(ComplianceError):
        client.validate()


def test_필수_파라미터가_빠지면_422_를_설명과_함께_올린다(client, session):
    from conftest import FakeResponse
    from compliance import ParameterError

    session.get = lambda *a, **k: FakeResponse(422, body={"detail": [
        {"type": "missing", "loc": ["query", "event_type"], "msg": "Field required"},
        {"type": "missing", "loc": ["query", "after"], "msg": "Field required"},
    ]})
    with pytest.raises(ParameterError) as caught:
        client.list_page()
    assert "422" in str(caught.value)
    assert "query.event_type: Field required" in str(caught.value)


def test_목록_조회는_after_를_항상_채워_보낸다(client, session):
    session.pages = [{"data": [], "has_more": False}]
    client.list_page(event_type="CONVERSATION_LOG")
    assert session.calls[0]["params"]["after"].endswith("Z")


def test_통하는_event_type_하나만_있어도_검증은_통과한다(client, session):
    session.event_types_ok = {"AUTH_LOG"}          # 앞 후보들은 전부 400
    assert client.validate()["event_type"] == "AUTH_LOG"


def test_모든_후보가_400_이면_마지막_오류를_올린다(client, session):
    from compliance import BadRequestError

    session.event_types_ok = set()
    with pytest.raises(BadRequestError):
        client.validate()
