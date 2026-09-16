"""웹 서버(HTTP API) 테스트 - 실제로 서버를 띄워 요청한다."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from conftest import needs_ffmpeg
from webrec.webserver import WebrecApp, create_server


@pytest.fixture
def app(tmp_path):
    return WebrecApp(
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "rec",
        log_dir=tmp_path / "logs",
    )


@pytest.fixture
def server(app):
    """127.0.0.1 의 빈 포트에 서버를 띄운다."""
    httpd = create_server(app, "127.0.0.1", 0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}", app
    finally:
        httpd.shutdown()
        httpd.server_close()


def call(base: str, path: str, method: str = "GET", payload: dict | None = None):
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        base + path, method=method, data=data,
        headers={"Content-Type": "application/json"} if data else {},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            body = response.read()
            parsed = json.loads(body) if body and b"{" in body[:2] else body
            return response.status, parsed
    except urllib.error.HTTPError as exc:
        body = exc.read()
        try:
            return exc.code, json.loads(body)
        except json.JSONDecodeError:
            return exc.code, body


def _payload(**overrides):
    payload = {
        "url": "https://example.com/live",
        "repeat": "once",
        "start": (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M"),
        "duration": "30m",
        "name": "테스트예약",
    }
    payload.update(overrides)
    return payload


# ------------------------------------------------------------------ 기본 화면
def test_index_page_is_served(server):
    base, _ = server
    status, body = call(base, "/")
    assert status == 200
    assert "예약 녹화" in body.decode("utf-8")


def test_state_is_empty_at_first(server):
    base, _ = server
    status, state = call(base, "/api/state")
    assert status == 200
    assert state["jobs"] == [] and state["recordings"] == []
    assert "ffmpeg" in state["tools"]


def test_unknown_path_returns_404(server):
    base, _ = server
    status, _ = call(base, "/%EC%97%86%EB%8A%94%EC%A3%BC%EC%86%8C")
    assert status == 404


# -------------------------------------------------------------------- 예약
def test_create_job(server):
    base, _ = server
    status, job = call(base, "/api/jobs", "POST", _payload())
    assert status == 201
    assert job["name"] == "테스트예약"
    assert job["duration_label"] == "30분"
    assert job["next_run"] is not None
    assert job["preflight"]["duration"] == 10          # 기본 10초 샘플링

    _, state = call(base, "/api/state")
    assert len(state["jobs"]) == 1


def test_create_job_without_url_is_rejected(server):
    base, _ = server
    status, body = call(base, "/api/jobs", "POST", _payload(url=""))
    assert status == 400
    assert "주소" in body["error"]


def test_create_job_with_bad_duration_is_rejected(server):
    base, _ = server
    status, body = call(base, "/api/jobs", "POST", _payload(duration="한시간쯤"))
    assert status == 400
    assert "duration" in body["error"] or "해석" in body["error"]


def test_create_job_without_time_is_rejected(server):
    base, _ = server
    status, body = call(base, "/api/jobs", "POST", _payload(start=""))
    assert status == 400
    assert "시작 시각" in body["error"]


def test_repeating_job_uses_cron(server):
    base, _ = server
    status, job = call(base, "/api/jobs", "POST",
                       _payload(repeat="cron", cron="0 9 * * mon", start=""))
    assert status == 201
    assert job["cron"] == "0 9 * * mon"
    assert job["next_run"] is not None


def test_bad_cron_is_rejected(server):
    base, _ = server
    status, body = call(base, "/api/jobs", "POST",
                        _payload(repeat="cron", cron="매주 월요일", start=""))
    assert status == 400
    assert "cron" in body["error"]


def test_pause_resume_and_delete(server):
    base, _ = server
    _, job = call(base, "/api/jobs", "POST", _payload())

    assert call(base, f"/api/jobs/{job['id']}/pause", "POST")[0] == 200
    _, state = call(base, "/api/state")
    assert state["jobs"][0]["enabled"] is False

    call(base, f"/api/jobs/{job['id']}/resume", "POST")
    _, state = call(base, "/api/state")
    assert state["jobs"][0]["enabled"] is True

    assert call(base, f"/api/jobs/{job['id']}", "DELETE")[0] == 200
    _, state = call(base, "/api/state")
    assert state["jobs"] == []


def test_delete_missing_job_returns_404(server):
    base, _ = server
    assert call(base, "/api/jobs/nosuchid", "DELETE")[0] == 404


# -------------------------------------------------------------------- 파일
def test_download_rejects_path_traversal(server, tmp_path):
    """'../' 로 다른 폴더 파일을 받아가지 못해야 한다."""
    base, app = server
    secret = tmp_path / "secret.txt"
    secret.write_text("비밀", encoding="utf-8")

    status, _ = call(base, "/recordings/%2e%2e%2fsecret.txt")
    assert status == 404


def test_download_serves_recording(server):
    base, app = server
    target = app.output_dir / "샘플.mkv"
    target.write_bytes(b"\x00" * 2048)

    status, body = call(base, "/recordings/%EC%83%98%ED%94%8C.mkv")
    assert status == 200
    assert len(body) == 2048

    _, state = call(base, "/api/state")
    assert state["recordings"][0]["name"] == "샘플.mkv"


# -------------------------------------------------------------------- 설정
def test_settings_are_saved_and_password_is_kept(server):
    base, app = server
    call(base, "/api/settings", "POST", {
        "smtp": {"host": "smtp.test", "port": 587, "username": "me@test", "password": "비밀번호-abc123"},
        "notify_to": "me@test",
    })
    assert app.smtp().password == "비밀번호-abc123"

    # 비밀번호 칸을 비워서 저장하면 기존 값을 유지한다
    call(base, "/api/settings", "POST", {
        "smtp": {"host": "smtp.test", "port": 465, "username": "me@test", "password": ""},
    })
    assert app.smtp().password == "비밀번호-abc123"
    assert app.smtp().port == 465

    _, state = call(base, "/api/state")
    assert state["mail"]["configured"] is True
    assert "비밀번호-abc123" not in json.dumps(state, ensure_ascii=False)  # 비밀번호는 안 나간다


def test_test_mail_without_settings_is_rejected(server):
    base, _ = server
    status, body = call(base, "/api/test-mail", "POST")
    assert status == 400
    assert "메일 설정" in body["error"]


# ---------------------------------------------------------------- 실제 실행
@needs_ffmpeg
def test_scheduled_job_runs_and_appears_in_recordings(server, media_server):
    """웹으로 등록한 예약이 실제로 녹화되어 목록에 뜨는지 확인한다."""
    base, app = server
    app.scheduler.start()
    try:
        start = (datetime.now() + timedelta(seconds=3)).strftime("%Y-%m-%dT%H:%M:%S")
        status, job = call(base, "/api/jobs", "POST", _payload(
            url=f"{media_server}/live.mp4", start=start, duration="4s",
            backend="stream", name="웹통합테스트",
            preflight_enabled=True, preflight_duration=3, preflight_lead=2,
        ))
        assert status == 201

        deadline = time.time() + 90
        seen = []
        while time.time() < deadline:
            _, state = call(base, "/api/state")
            current = state["jobs"][0]["status"]
            if current not in seen:
                seen.append(current)
            if current in ("완료", "실패"):
                break
            time.sleep(1)

        _, state = call(base, "/api/state")
        job_view = state["jobs"][0]
        assert job_view["status"] == "완료", job_view
        assert "녹화중" in seen                     # 진행 상태가 화면에 반영됐다

        run = job_view["runs"][0]
        assert run["ok"] is True
        assert run["duration_sec"] >= 3
        assert state["recordings"][0]["name"] == run["file"]

        # 녹화된 파일을 웹에서 받을 수 있다
        status, body = call(base, state["recordings"][0]["url"])
        assert status == 200 and len(body) > 10_000
    finally:
        app.scheduler.stop()
