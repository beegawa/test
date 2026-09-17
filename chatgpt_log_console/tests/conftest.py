"""테스트 공통 준비물.

실제 API 를 부르지 않도록 requests.Session 흉내를 내는 FakeSession 을 쓴다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from compliance import ComplianceClient  # noqa: E402
from store import LogStore  # noqa: E402


class FakeResponse:
    def __init__(self, status_code=200, body=None, text=None, headers=None):
        self.status_code = status_code
        self._body = body
        self.text = text if text is not None else (json.dumps(body) if body is not None else "")
        self.headers = headers or {}

    def json(self):
        if self._body is None:
            raise ValueError("not json")
        return self._body


class FakeSession:
    """경로별 응답을 미리 심어 두고, 호출 기록을 남긴다."""

    def __init__(self):
        self.pages: list[dict] = []          # 목록 응답을 순서대로 돌려준다
        self.logs: dict[str, str] = {}       # log_id -> JSONL 본문
        self.event_types_ok: set[str] | None = None   # None 이면 전부 허용
        self.calls: list[dict] = []
        self.status_queue: list[int] = []    # 강제로 낼 상태코드(429 등)

    def get(self, url, headers=None, params=None, timeout=None, allow_redirects=True, stream=False):
        params = params or {}
        self.calls.append({"url": url, "params": dict(params), "headers": dict(headers or {})})

        if self.status_queue:
            status = self.status_queue.pop(0)
            return FakeResponse(status, text=f"forced {status}", headers={"Retry-After": "0"})

        if "/logs/" in url:
            log_id = url.rsplit("/logs/", 1)[1]
            if log_id not in self.logs:
                return FakeResponse(404, text="not found")
            return FakeResponse(200, text=self.logs[log_id])

        event_type = params.get("event_type")
        if event_type and self.event_types_ok is not None and event_type not in self.event_types_ok:
            return FakeResponse(400, text=f"unknown event_type {event_type}")
        empty = {"data": [], "has_more": False, "last_end_time": None}
        # limit=1 은 키 검증·event_type 후보 탐지용 호출이라 준비해 둔 페이지를 쓰지 않는다.
        if params.get("limit") == 1 or not self.pages:
            return FakeResponse(200, body=empty)
        return FakeResponse(200, body=self.pages.pop(0))


@pytest.fixture
def session() -> FakeSession:
    return FakeSession()


@pytest.fixture
def client(session) -> ComplianceClient:
    return ComplianceClient(
        "sk-test-key",
        base_url="https://example.test/v1/compliance",
        workspace_id="ws_1",
        org_id=None,
        session=session,
        sleep=lambda _seconds: None,
    )


@pytest.fixture
def store(tmp_path) -> LogStore:
    with LogStore(tmp_path / "logs.db") as opened:
        yield opened


def jsonl(*records) -> str:
    return "\n".join(json.dumps(record, ensure_ascii=False) for record in records)
