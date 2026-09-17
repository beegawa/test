"""웹 콘솔 엔드포인트."""

import time

import pytest
from conftest import jsonl

import keystore
import settings
from app import create_app
from compliance import AuthError, ComplianceClient


@pytest.fixture
def 앱(tmp_path, monkeypatch, session):
    monkeypatch.setenv("CHATGPT_LOG_NO_KEYRING", "1")
    monkeypatch.delenv("CHATGPT_ADMIN_KEY", raising=False)
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    monkeypatch.setattr(keystore, "DATA_DIR", tmp_path)

    def factory(key):
        return ComplianceClient(key, base_url="https://example.test", workspace_id="ws_1",
                                org_id=None, session=session, sleep=lambda _s: None)

    application = create_app(database=tmp_path / "logs.db", client_factory=factory)
    application.config["TESTING"] = True
    return application


@pytest.fixture
def cli(앱):
    return 앱.test_client()


def 페이지(ids, cursor="2026-09-17T00:00:00Z"):
    return {"data": [{"id": i} for i in ids], "has_more": False, "last_end_time": cursor}


def 수집완료까지(cli, timeout=5.0):
    마감 = time.time() + timeout
    while time.time() < 마감:
        body = cli.get("/api/pull/status").get_json()
        if not body["pull"]["running"]:
            return body
        time.sleep(0.02)
    raise AssertionError("수집이 끝나지 않았습니다.")


# ---------------------------------------------------------------- 상태/키
def test_처음에는_키가_없다고_알려준다(cli):
    body = cli.get("/api/status").get_json()
    assert body["key_saved"] is False
    assert body["scope"].startswith("workspace:")
    assert body["stats"]["total"] == 0


def test_키는_검증에_성공해야_저장된다(cli, session):
    assert cli.post("/api/save-key", json={"key": "sk-admin-1234567890"}).status_code == 200
    assert cli.get("/api/status").get_json()["key_saved"] is True
    assert keystore.load_key() == "sk-admin-1234567890"


def test_401_이면_저장하지_않는다(cli, session):
    session.status_queue = [401]
    response = cli.post("/api/save-key", json={"key": "틀린키"})
    assert response.status_code == 401
    assert keystore.load_key() is None


def test_403_권한_부족도_저장하지_않는다(cli, session):
    session.status_queue = [403]
    assert cli.post("/api/save-key", json={"key": "권한없는키"}).status_code == 401
    assert keystore.load_key() is None


def test_빈_키는_400(cli):
    assert cli.post("/api/save-key", json={"key": "  "}).status_code == 400


def test_키_삭제(cli):
    cli.post("/api/save-key", json={"key": "sk-admin-1234567890"})
    assert cli.post("/api/forget-key").get_json()["removed"] is True
    assert cli.get("/api/status").get_json()["key_saved"] is False


def test_키가_없으면_수집은_401(cli):
    assert cli.post("/api/pull", json={"days": 1}).status_code == 401


# ---------------------------------------------------------------- 수집
def test_수집하면_DB_에_쌓이고_미리보기가_나온다(cli, session):
    cli.post("/api/save-key", json={"key": "sk-admin-1234567890"})
    session.event_types_ok = {"CONVERSATION_LOG"}
    session.pages = [페이지(["log_1"])]
    session.logs["log_1"] = jsonl(
        {"id": "e1", "created_at": "2026-09-16T00:00:00Z", "user_email": "a@x.com", "content": "안녕"}
    )

    assert cli.post("/api/pull", json={"days": 1}).status_code == 202
    body = 수집완료까지(cli)

    assert body["pull"]["result"]["saved"] == 1
    assert body["stats"]["total"] == 1
    assert body["preview"][0]["user"] == "a@x.com"
    assert "raw" not in body["preview"][0]          # 표에는 원본을 싣지 않는다


def test_수집_중_같은_요청은_409(cli, session, monkeypatch):
    cli.post("/api/save-key", json={"key": "sk-admin-1234567890"})
    import app as app_module

    쉬는중 = {"멈춤": False}

    def 느린수집(*_args, **kwargs):
        while not 쉬는중["멈춤"]:
            time.sleep(0.01)
        from collector import CollectResult
        return CollectResult()

    monkeypatch.setattr(app_module, "collect", 느린수집)
    assert cli.post("/api/pull", json={"days": 1}).status_code == 202
    try:
        assert cli.post("/api/pull", json={"days": 1}).status_code == 409
    finally:
        쉬는중["멈춤"] = True
        수집완료까지(cli)


def test_수집_실패는_화면에_오류로_남는다(cli, session):
    cli.post("/api/save-key", json={"key": "sk-admin-1234567890"})
    session.event_types_ok = {"CONVERSATION_LOG"}
    session.status_queue = [401]
    cli.post("/api/pull", json={"days": 1})
    body = 수집완료까지(cli)
    assert body["pull"]["error"] and "401" in body["pull"]["error"]


# ---------------------------------------------------------------- 검색/엑셀
@pytest.fixture
def 데이터(앱):
    앱.config["STORE"].add_many([
        {"id": "a", "event_type": "CONVERSATION_LOG", "ts": "2026-09-01T00:00:00Z",
         "user": "hong@shinwon.com", "content": "휴가 규정 알려줘", "summary": "휴가 규정 알려줘",
         "source_log_id": "log_1", "raw": {"id": "a"}},
        {"id": "b", "event_type": "CONVERSATION_LOG", "ts": "2026-09-15T00:00:00Z",
         "user": "kim@shinwon.com", "content": "매출 보고서 양식", "summary": "매출 보고서 양식",
         "source_log_id": "log_2", "raw": {"id": "b"}},
    ])
    return 앱


def test_기간_사용자_키워드로_검색한다(cli, 데이터):
    rows = cli.get("/api/search?q=매출").get_json()["rows"]
    assert [r["id"] for r in rows] == ["b"]
    rows = cli.get("/api/search?user=hong").get_json()["rows"]
    assert [r["id"] for r in rows] == ["a"]
    rows = cli.get("/api/search?from=2026-09-10T00:00:00Z").get_json()["rows"]
    assert [r["id"] for r in rows] == ["b"]
    assert cli.get("/api/search").get_json()["total"] == 2


def test_자세히_보기는_원본_JSON_까지_준다(cli, 데이터):
    row = cli.get("/api/log/a").get_json()["row"]
    assert row["content"] == "휴가 규정 알려줘"
    assert '"id": "a"' in row["raw"]
    assert cli.get("/api/log/없는id").status_code == 404


def test_엑셀은_검색_조건_그대로_내려준다(cli, 데이터):
    response = cli.get("/api/download.xlsx?q=매출")
    assert response.status_code == 200
    assert response.headers["Content-Disposition"].startswith("attachment")
    assert response.data[:2] == b"PK"        # xlsx 는 zip
    assert len(response.data) > 1000


def test_사용자_목록(cli, 데이터):
    assert set(cli.get("/api/users").get_json()["users"]) == {"hong@shinwon.com", "kim@shinwon.com"}


def test_화면이_열린다(cli):
    response = cli.get("/")
    assert response.status_code == 200
    assert "ChatGPT 대화 로그 콘솔" in response.get_data(as_text=True)
