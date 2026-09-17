"""SQLite 누적 저장·검색."""

import json

from store import LogStore


def rec(**over):
    base = {
        "id": "evt_1", "event_type": "CONVERSATION_LOG", "ts": "2026-09-10T03:00:00Z",
        "user": "hong@shinwon.com", "content": "매출 보고서 양식", "summary": "매출 보고서 양식",
        "source_log_id": "log_a", "raw": {"id": "evt_1"},
    }
    base.update(over)
    # 내용만 바꾼 경우 요약도 같이 따라가게 한다(실제 수집 결과와 동일한 모양).
    if "content" in over and "summary" not in over:
        base["summary"] = over["content"]
    return base


def test_같은_id_는_두_번_저장되지_않는다(store):
    assert store.add_many([rec(), rec(id="evt_2")]) == 2
    assert store.add_many([rec(), rec(id="evt_2"), rec(id="evt_3")]) == 1
    assert store.stats()["total"] == 3


def test_raw_는_JSON_문자열로_보관된다(store):
    store.add_many([rec(raw={"a": "값", "b": [1, 2]})])
    row = store.search()[0]
    assert json.loads(row["raw"]) == {"a": "값", "b": [1, 2]}


def test_기간_사용자_키워드로_검색한다(store):
    store.add_many([
        rec(id="a", ts="2026-09-01T00:00:00Z", user="hong@shinwon.com", content="휴가 규정"),
        rec(id="b", ts="2026-09-15T00:00:00Z", user="kim@shinwon.com", content="매출 보고서"),
        rec(id="c", ts="2026-09-20T00:00:00Z", user="kim@shinwon.com", content="영문 메일 작성"),
    ])
    assert [r["id"] for r in store.search(start="2026-09-10T00:00:00Z")] == ["c", "b"]
    assert [r["id"] for r in store.search(end="2026-09-10T00:00:00Z")] == ["a"]
    assert [r["id"] for r in store.search(user="kim")] == ["c", "b"]
    assert [r["id"] for r in store.search(keyword="매출")] == ["b"]
    assert store.count(user="kim") == 2


def test_키워드는_원본_JSON_도_뒤진다(store):
    store.add_many([rec(id="a", content="", summary="", raw={"note": "특이사항"})])
    assert len(store.search(keyword="특이사항")) == 1


def test_최신순으로_정렬하고_limit_을_지킨다(store):
    store.add_many([rec(id=f"e{i}", ts=f"2026-09-{i:02d}T00:00:00Z") for i in range(1, 6)])
    rows = store.search(limit=2)
    assert [r["id"] for r in rows] == ["e5", "e4"]


def test_통계와_마지막_시각(store):
    store.add_many([
        rec(id="a", ts="2026-09-01T00:00:00Z", event_type="AUTH_LOG", user="a@x.com"),
        rec(id="b", ts="2026-09-09T00:00:00Z", event_type="CONVERSATION_LOG", user="b@x.com"),
    ])
    stats = store.stats()
    assert stats == {
        "total": 2, "oldest": "2026-09-01T00:00:00Z", "newest": "2026-09-09T00:00:00Z",
        "by_event": {"AUTH_LOG": 1, "CONVERSATION_LOG": 1}, "users": 2,
    }
    assert store.latest_ts() == "2026-09-09T00:00:00Z"
    assert store.latest_ts("AUTH_LOG") == "2026-09-01T00:00:00Z"
    assert store.users() == ["a@x.com", "b@x.com"]


def test_id_로_한_건을_꺼낸다(store):
    store.add_many([rec(id="a")])
    assert store.get("a")["user"] == "hong@shinwon.com"
    assert store.get("없는id") is None


def test_커서와_meta_는_재시작_후에도_남는다(tmp_path):
    path = tmp_path / "logs.db"
    with LogStore(path) as first:
        first.set_cursor("CONVERSATION_LOG", "2026-09-17T00:00:00Z")
        first.set_meta("event_types", ["CONVERSATION_LOG"])
    with LogStore(path) as second:
        assert second.get_cursor("CONVERSATION_LOG") == "2026-09-17T00:00:00Z"
        assert second.get_meta("event_types") == ["CONVERSATION_LOG"]
        assert second.get_meta("없는키", "기본값") == "기본값"


def test_id_없는_레코드는_건너뛴다(store):
    assert store.add_many([{"id": "", "content": "x"}, {}]) == 0


def test_DB_파일은_소유자만_읽는다(tmp_path):
    path = tmp_path / "logs.db"
    with LogStore(path):
        assert oct(path.stat().st_mode & 0o777) == "0o600"
