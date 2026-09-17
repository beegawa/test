"""통합 테스트 - 진짜 HTTP 서버를 띄워 '키 저장 → 수집 → 검색 → 엑셀' 전 과정을 돌린다.

FakeSession 이 아니라 requests 와 Flask 를 그대로 태워서, 헤더·쿼리·페이지네이션·
JSONL 파싱이 실제 통신에서도 맞는지 확인한다.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from urllib.parse import parse_qs, urlparse

import pytest

import keystore
import settings
from app import create_app
from compliance import ComplianceClient

WORKSPACE = "ws_e2e"
KEY = "sk-admin-e2e-0001"

# 사용자 2명 × 각 로그 2줄. 마지막 페이지에서 has_more 가 꺼진다.
LOGS = {
    "log_1": [
        {"id": "e1", "event_type": "CONVERSATION_LOG", "created_at": "2026-09-16T01:00:00Z",
         "user_email": "hong@shinwon.com",
         "messages": [{"role": "user", "content": "휴가 규정 알려줘"},
                      {"role": "assistant", "content": "취업규칙 12조를 보세요."}]},
        {"id": "e2", "event_type": "CONVERSATION_LOG", "created_at": "2026-09-16T02:00:00Z",
         "user_email": "hong@shinwon.com",
         "messages": [{"role": "user", "content": "영문 메일 다듬어줘"}]},
    ],
    "log_2": [
        {"id": "e3", "event_type": "CONVERSATION_LOG", "created_at": "2026-09-16T03:00:00Z",
         "user_email": "kim@shinwon.com",
         "messages": [{"role": "user", "content": "매출 보고서 양식 만들어줘"}]},
    ],
}


class StubHandler(BaseHTTPRequestHandler):
    """Compliance Logs Platform 흉내. 두 페이지로 나눠 준다."""

    def log_message(self, *args):  # 테스트 출력 조용히
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        params = {k: v[0] for k, v in parse_qs(parsed.query).items()}

        if self.headers.get("Authorization") != f"Bearer {KEY}":
            return self._send(401, {"error": "invalid key"})
        if f"/workspaces/{WORKSPACE}/logs" not in parsed.path:
            return self._send(404, {"error": "unknown scope"})

        tail = parsed.path.split("/logs", 1)[1].strip("/")
        if tail:                                    # 개별 로그 다운로드(JSONL)
            if tail not in LOGS:
                return self._send(404, {"error": "no such log"})
            body = "\n".join(json.dumps(r, ensure_ascii=False) for r in LOGS[tail])
            return self._send(200, body, content_type="application/jsonl")

        if params.get("event_type") not in (None, "CONVERSATION_LOG"):
            return self._send(400, {"error": "unknown event_type"})
        if params.get("limit") == "1":               # 키 검증 / 후보 탐지
            return self._send(200, {"data": [], "has_more": False})
        if not params.get("after") or "PAGE2" not in params.get("after", ""):
            return self._send(200, {"data": [{"id": "log_1"}], "has_more": True,
                                    "last_end_time": "2026-09-16T02:00:00Z-PAGE2"})
        return self._send(200, {"data": [{"id": "log_2"}], "has_more": False,
                                "last_end_time": "2026-09-16T03:00:00Z"})

    def _send(self, status, body, content_type="application/json"):
        payload = (body if isinstance(body, str) else json.dumps(body)).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


@pytest.fixture
def 스텁서버():
    server = ThreadingHTTPServer(("127.0.0.1", 0), StubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


@pytest.fixture
def cli(tmp_path, monkeypatch, 스텁서버):
    monkeypatch.setenv("CHATGPT_LOG_NO_KEYRING", "1")
    monkeypatch.delenv("CHATGPT_ADMIN_KEY", raising=False)
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    monkeypatch.setattr(keystore, "DATA_DIR", tmp_path)
    app = create_app(
        database=tmp_path / "logs.db",
        client_factory=lambda key: ComplianceClient(
            key, base_url=스텁서버, workspace_id=WORKSPACE, org_id=None
        ),
    )
    app.config["TESTING"] = True
    return app.test_client()


def 수집완료까지(cli, timeout=10.0):
    마감 = time.time() + timeout
    while time.time() < 마감:
        body = cli.get("/api/pull/status").get_json()
        if not body["pull"]["running"]:
            return body
        time.sleep(0.05)
    raise AssertionError("수집이 끝나지 않았습니다.")


def test_키저장부터_엑셀까지_한_번에(cli):
    # 1) 틀린 키는 거절당하고 저장되지 않는다
    assert cli.post("/api/save-key", json={"key": "sk-wrong"}).status_code == 401
    assert cli.get("/api/status").get_json()["key_saved"] is False

    # 2) 맞는 키는 검증 후 저장된다
    assert cli.post("/api/save-key", json={"key": KEY}).status_code == 200
    assert cli.get("/api/status").get_json()["key_saved"] is True

    # 3) 수집 - 페이지 2장, 로그 2건, 레코드 3건
    assert cli.post("/api/pull", json={"days": 7}).status_code == 202
    body = 수집완료까지(cli)
    result = body["pull"]["result"]
    assert result["event_types"] == ["CONVERSATION_LOG"]
    assert (result["fetched"], result["records"], result["saved"]) == (2, 3, 3)
    assert not result["errors"]
    assert body["stats"]["total"] == 3
    assert len(body["preview"]) == 3

    # 4) 대화 내용이 사람이 읽을 수 있게 저장됐다
    rows = cli.get("/api/search?q=휴가").get_json()["rows"]
    assert len(rows) == 1
    assert "사용자: 휴가 규정 알려줘" in rows[0]["content"]

    # 5) 사용자·기간으로도 걸러진다
    assert cli.get("/api/search?user=kim").get_json()["total"] == 1
    assert cli.get("/api/search?from=2026-09-16T02:30:00Z").get_json()["total"] == 1

    # 6) 다시 수집해도 중복은 안 쌓인다 (30일 넘긴 과거 데이터를 지키는 핵심 성질)
    cli.post("/api/pull", json={"days": 7})
    다시 = 수집완료까지(cli)
    assert 다시["pull"]["result"]["saved"] == 0
    assert 다시["stats"]["total"] == 3

    # 7) 엑셀 - 조건 없이 부르면 '마지막 검색 결과' 를, 조건을 주면 그 조건대로 내려준다
    from openpyxl import load_workbook

    마지막검색 = load_workbook(BytesIO(cli.get("/api/download.xlsx").data)).active
    assert 마지막검색.max_row == 2                   # 머리글 1 + 직전 검색 결과 1건

    response = cli.get("/api/download.xlsx?q=")
    assert response.status_code == 200
    sheet = load_workbook(BytesIO(response.data)).active
    assert sheet.max_row == 4                       # 머리글 1 + 3건
    assert sheet.cell(row=1, column=1).value == "시간(UTC)"
    assert "hong@shinwon.com" in {sheet.cell(row=r, column=3).value for r in range(2, 5)}

    # 8) 키를 지우면 다시 수집할 수 없다
    cli.post("/api/forget-key")
    assert cli.post("/api/pull", json={"days": 1}).status_code == 401
