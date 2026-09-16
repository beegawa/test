"""접속 확인 테스트.

브라우저 캡처는 페이지가 안 열려도 '에러 페이지'가 녹화되기 때문에,
캡처 전에 주소가 살아 있는지 확인하는 단계가 특히 중요하다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import needs_ffmpeg
from webrec.config import build_config
from webrec.preflight import run_preflight
from webrec.runner import JobRunner
from webrec.sites import check_reachable


def test_reachable_url(media_server):
    level, detail = check_reachable(f"{media_server}/live.mp4")
    assert level == "ok"
    assert "200" in detail


def test_connection_refused_is_fatal():
    level, detail = check_reachable("http://127.0.0.1:9/nothing", timeout=3)
    assert level == "fail"
    assert "접속 불가" in detail


def test_unknown_host_is_fatal():
    level, _ = check_reachable("http://그런호스트는없습니다.invalid/live", timeout=5)
    assert level == "fail"


def test_http_error_is_only_a_warning(media_server):
    """404 는 봇 차단일 수도 있어 경고로만 본다."""
    level, detail = check_reachable(f"{media_server}/없는파일.mp4")
    assert level == "warn"
    assert "404" in detail


def _job(url: str, tmp_path: Path, **overrides):
    raw = {
        "name": "접속테스트", "url": url, "duration": "10s", "backend": "stream",
        "output_dir": str(tmp_path / "rec"),
        "preflight": {"duration": 3, "lead_seconds": 0},
        **overrides,
    }
    return build_config({"jobs": [raw]}, require_schedule=False).jobs[0]


def test_preflight_fails_fast_when_url_is_dead(tmp_path):
    """접속이 안 되면 샘플을 녹화하지 않고 바로 실패로 보고한다."""
    report = run_preflight(_job("http://127.0.0.1:9/dead", tmp_path))

    assert not report.ok
    assert report.sample_path is None          # 녹화 시도조차 하지 않았다
    assert "접속할 수 없습니다" in report.error
    assert report.checks[0].name == "접속 확인"
    assert "접속 확인" in report.summary()


@needs_ffmpeg
def test_preflight_passes_connectivity_then_records(media_server, tmp_path):
    report = run_preflight(_job(f"{media_server}/live.mp4", tmp_path))
    assert report.ok, report.summary()
    assert report.checks[0].ok
    assert report.verification is not None


def test_dead_url_sends_failure_mail(tmp_path, mailer):
    """접속 불가 사실이 메일로 전달된다."""
    job = _job("http://127.0.0.1:9/dead", tmp_path,
               notify={"on": ["preflight_failed", "failed"]},
               preflight={"duration": 3, "lead_seconds": 0, "abort_on_failure": True})
    outcome = JobRunner(job, mailer, log_dir=tmp_path / "logs").run()

    assert not outcome.ok
    bodies = "\n".join(item["body"] for item in mailer.sent)
    assert "접속 확인" in bodies
    assert any("사전 점검 실패" in s for s in mailer.subjects())


def test_non_ascii_url_is_encoded(media_server):
    """한글이 든 주소도 그대로 처리한다(퍼센트 인코딩)."""
    from webrec.sites import encode_url

    assert encode_url("http://h/한글.mp4") == "http://h/%ED%95%9C%EA%B8%80.mp4"
    assert encode_url("http://h/ascii.mp4?a=1&b=2") == "http://h/ascii.mp4?a=1&b=2"

    level, detail = check_reachable(f"{media_server}/없는파일.mp4")
    assert level == "warn" and "404" in detail
