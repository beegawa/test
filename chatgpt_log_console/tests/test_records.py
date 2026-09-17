"""원본 JSON → DB 행 변환."""

from records import flatten_content, normalize, normalize_ts, normalize_user, summarize


def test_대화_메시지를_사람이_읽는_평문으로_편다():
    record = normalize(
        {
            "id": "evt_1",
            "event_type": "CONVERSATION_LOG",
            "created_at": "2026-09-17T01:02:03Z",
            "user": {"email": "hong@shinwon.com"},
            "messages": [
                {"role": "user", "content": "매출 보고서 양식 알려줘"},
                {"role": "assistant", "content": {"parts": ["네, 아래 양식을 쓰세요."]}},
            ],
        },
        log_id="log_a",
    )
    assert record["id"] == "evt_1"
    assert record["ts"] == "2026-09-17T01:02:03Z"
    assert record["user"] == "hong@shinwon.com"
    assert "사용자: 매출 보고서 양식 알려줘" in record["content"]
    assert "ChatGPT: 네, 아래 양식을 쓰세요." in record["content"]


def test_고유_id_가_없으면_로그id와_줄번호로_만든다():
    first = normalize({"text": "a"}, log_id="log_b", index=0)
    second = normalize({"text": "b"}, log_id="log_b", index=1)
    assert first["id"] == "log_b#0"
    assert second["id"] == "log_b#1"


def test_event_type_이_원본에_없으면_요청한_타입을_쓴다():
    record = normalize({"text": "x"}, log_id="log_c", event_type_hint="AUTH_LOG")
    assert record["event_type"] == "AUTH_LOG"


def test_시각은_epoch_와_ISO_모두_UTC_로_통일된다():
    assert normalize_ts(1758070923) == "2025-09-17T01:02:03Z"
    assert normalize_ts(1758070923000) == normalize_ts(1758070923)   # 밀리초
    assert normalize_ts("2026-09-17T10:00:00+09:00") == "2026-09-17T01:00:00Z"
    assert normalize_ts(None) == ""


def test_해석_못_하는_시각은_원문을_남긴다():
    assert normalize_ts("어제") == "어제"


def test_사용자는_dict_면_이메일_이름_id_순으로_고른다():
    assert normalize_user({"name": "홍길동", "id": "u1"}) == "홍길동"
    assert normalize_user({"email": "a@b.com", "name": "홍길동"}) == "a@b.com"
    assert normalize_user("u_9") == "u_9"
    assert normalize_user(None) == ""


def test_필드를_못_찾아도_예외없이_빈_값으로_둔다():
    record = normalize({"완전히": {"낯선": "구조"}}, log_id="log_d")
    assert record["ts"] == "" and record["user"] == ""
    assert record["raw"] == {"완전히": {"낯선": "구조"}}


def test_요약은_한_줄로_자른다():
    assert summarize("가나다\n라마바") == "가나다 라마바"
    assert summarize("가" * 300).endswith("…")
    assert len(summarize("가" * 300)) == 160


def test_중첩된_리스트도_평문으로_편다():
    assert flatten_content([{"content": ["하나", "둘"]}, "셋"]) == "하나\n둘\n셋"
