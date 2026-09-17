"""수집 절차 - 목록 → 다운로드 → 정리 → 누적."""

import threading

from conftest import jsonl

from collector import collect, resolve_event_types


def 페이지(ids, *, has_more=False, cursor="2026-09-17T00:00:00Z"):
    return {"data": [{"id": i} for i in ids], "has_more": has_more, "last_end_time": cursor}


def test_받은_로그를_DB_에_쌓고_결과를_알려준다(client, session, store):
    session.event_types_ok = {"CONVERSATION_LOG"}
    session.pages = [페이지(["log_1", "log_2"])]
    session.logs["log_1"] = jsonl({"id": "e1", "created_at": "2026-09-16T00:00:00Z",
                                   "user_email": "a@x.com", "content": "안녕"})
    session.logs["log_2"] = jsonl({"id": "e2", "created_at": "2026-09-16T01:00:00Z",
                                   "user_email": "b@x.com", "content": "보고서"},
                                  {"id": "e3", "created_at": "2026-09-16T02:00:00Z",
                                   "user_email": "b@x.com", "content": "메일"})

    result = collect(client, store, days=7)

    assert result.event_types == ["CONVERSATION_LOG"]
    assert (result.listed, result.fetched, result.records, result.saved) == (2, 2, 3, 3)
    assert store.stats()["total"] == 3
    assert [r["user"] for r in store.search()] == ["b@x.com", "b@x.com", "a@x.com"]


def test_같은_로그를_다시_받아도_중복_저장되지_않는다(client, session, store):
    session.logs["log_1"] = jsonl({"id": "e1", "content": "x"})
    session.pages = [페이지(["log_1"])]
    first = collect(client, store, days=1, event_types=["CONVERSATION_LOG"])
    session.pages = [페이지(["log_1"])]
    second = collect(client, store, days=1, event_types=["CONVERSATION_LOG"])

    assert first.saved == 1
    assert second.saved == 0 and second.records == 1
    assert second.to_dict()["duplicates"] == 1
    assert store.stats()["total"] == 1


def test_기간_수집은_after_에_그_기간을_넣는다(client, session, store):
    session.pages = [페이지([])]
    collect(client, store, days=7, event_types=["CONVERSATION_LOG"])
    assert "after" in session.calls[0]["params"]


def test_증분_수집은_마지막_커서부터_이어받는다(client, session, store):
    session.pages = [페이지(["log_1"], cursor="2026-09-16T12:00:00Z")]
    session.logs["log_1"] = jsonl({"id": "e1", "created_at": "2026-09-16T11:00:00Z"})
    collect(client, store, days=7, event_types=["CONVERSATION_LOG"])
    assert store.get_cursor("CONVERSATION_LOG") == "2026-09-16T12:00:00Z"

    session.calls.clear()
    session.pages = [페이지([])]
    collect(client, store, incremental=True, event_types=["CONVERSATION_LOG"])
    assert session.calls[0]["params"]["after"] == "2026-09-16T12:00:00Z"


def test_다운로드_실패는_기록만_하고_나머지를_계속_받는다(client, session, store):
    session.pages = [페이지(["없는로그", "log_2"])]
    session.logs["log_2"] = jsonl({"id": "e2", "content": "살아남음"})
    result = collect(client, store, days=1, event_types=["CONVERSATION_LOG"])
    assert result.fetched == 1 and result.saved == 1
    assert len(result.errors) == 1 and "없는로그" in result.errors[0]


def test_상한에_닿으면_잘라내고_표시한다(client, session, store):
    session.pages = [페이지([f"log_{i}" for i in range(5)], has_more=True)]
    for i in range(5):
        session.logs[f"log_{i}"] = jsonl({"id": f"e{i}"})
    result = collect(client, store, days=1, event_types=["CONVERSATION_LOG"], max_logs=2)
    assert result.truncated is True and result.fetched == 2


def test_중지_신호를_받으면_그_자리에서_멈춘다(client, session, store):
    session.pages = [페이지([f"log_{i}" for i in range(5)])]
    for i in range(5):
        session.logs[f"log_{i}"] = jsonl({"id": f"e{i}"})
    cancel = threading.Event()
    cancel.set()
    result = collect(client, store, days=1, event_types=["CONVERSATION_LOG"], cancel=cancel)
    assert result.fetched == 0


def test_통하는_event_type_이_없으면_필터_없이_전체를_받는다(client, session, store):
    session.event_types_ok = set()                      # 모든 후보가 400
    session.pages = [페이지(["log_1"])]
    session.logs["log_1"] = jsonl({"id": "e1", "content": "전체수집"})

    result = collect(client, store, days=1)

    assert result.event_types == []
    assert result.saved == 1
    assert "event_type" not in session.calls[-1]["params"]


def test_event_type_탐지_결과는_DB_에_기억된다(client, session, store):
    session.event_types_ok = {"AUTH_LOG"}
    assert resolve_event_types(client, store) == ["AUTH_LOG"]

    session.calls.clear()
    assert resolve_event_types(client, store) == ["AUTH_LOG"]
    assert session.calls == []                          # 두 번째는 다시 찔러보지 않는다


def test_진행률_콜백이_중간_상태를_알려준다(client, session, store):
    session.pages = [페이지(["log_1"])]
    session.logs["log_1"] = jsonl({"id": "e1"})
    snapshots = []
    collect(client, store, days=1, event_types=["CONVERSATION_LOG"], progress=snapshots.append)
    assert snapshots and snapshots[-1]["saved"] == 1
