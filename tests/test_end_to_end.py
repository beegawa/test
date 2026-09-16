"""실제 ffmpeg 로 녹화까지 돌려보는 통합 테스트.

로컬 HTTP 서버가 영상을 제공하고, webrec 이 '사전 10초(테스트에서는 3초) 샘플링 ->
본 녹화 -> 검증 -> 메일 통보' 전 과정을 수행하는지 확인한다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import make_video, needs_ffmpeg
from webrec.config import build_config
from webrec.runner import JobRunner


def _make_job(url: str, tmp_path: Path, **overrides):
    raw = {
        "name": "통합테스트",
        "url": url,
        "duration": "6s",
        "start": "2030-01-01 10:00",
        "backend": "stream",
        "output_dir": str(tmp_path / "recordings"),
        "preflight": {"duration": 3, "lead_seconds": 0},
        "notify": {"on": ["preflight_passed", "preflight_failed", "started", "completed", "failed"]},
        "max_retries": 0,
    }
    raw.update(overrides)
    return build_config({"jobs": [raw]}).jobs[0]


@needs_ffmpeg
def test_full_flow_records_verifies_and_mails(media_server, tmp_path, mailer):
    job = _make_job(f"{media_server}/live.mp4", tmp_path)
    outcome = JobRunner(job, mailer, log_dir=tmp_path / "logs").run()

    # 1) 사전 점검이 먼저 수행되고 통과했다
    assert outcome.preflight is not None and outcome.preflight.ok, \
        outcome.preflight.summary() if outcome.preflight else "점검 없음"

    # 2) 본 녹화가 정상 종료되고 파일이 남았다
    assert outcome.ok, outcome.error
    assert outcome.output_path and Path(outcome.output_path).exists()
    assert outcome.verification is not None and outcome.verification.ok
    assert outcome.verification.metrics["duration_sec"] >= 5

    # 3) 점검/시작/완료 메일이 지정 주소로 나갔다
    subjects = mailer.subjects()
    assert any("사전 점검 정상" in s for s in subjects)
    assert any("녹화 시작" in s for s in subjects)
    assert any("녹화 완료" in s for s in subjects)
    assert all(item["to"] == ["travislee@shinwon.com"] for item in mailer.sent)

    # 4) 완료 메일에 저장 위치가 들어 있다
    completed = next(item for item in mailer.sent if "녹화 완료" in item["subject"])
    assert str(outcome.output_path) in completed["body"]


@needs_ffmpeg
def test_preflight_detects_black_screen_and_can_abort(media_server, tmp_path, mailer):
    """검은 화면만 나오는 소스는 사전 점검에서 걸러지고, 설정에 따라 녹화를 취소한다."""
    job = _make_job(
        f"{media_server}/black.mp4",
        tmp_path,
        preflight={"duration": 3, "lead_seconds": 0, "abort_on_failure": True},
    )
    outcome = JobRunner(job, mailer, log_dir=tmp_path / "logs").run()

    assert outcome.preflight is not None and not outcome.preflight.ok
    assert not outcome.ok
    assert outcome.output_path is None          # 본 녹화는 시작조차 하지 않았다
    subjects = mailer.subjects()
    assert any("사전 점검 실패" in s for s in subjects)
    assert any("녹화 취소" in s for s in subjects)


@needs_ffmpeg
def test_preflight_failure_does_not_block_recording_by_default(media_server, tmp_path, mailer):
    """기본 설정에서는 점검이 실패해도 본 녹화는 시도한다(방송 시작 전 점검 등)."""
    job = _make_job(f"{media_server}/black.mp4", tmp_path)
    outcome = JobRunner(job, mailer, log_dir=tmp_path / "logs").run()

    assert outcome.preflight is not None and not outcome.preflight.ok
    assert outcome.output_path is not None      # 녹화는 진행됐다
    assert any("사전 점검 실패" in w for w in outcome.warnings)


@needs_ffmpeg
def test_unreachable_url_reports_failure_by_mail(media_server, tmp_path, mailer):
    job = _make_job(f"{media_server}/없는파일.mp4", tmp_path, preflight={"enabled": False})
    outcome = JobRunner(job, mailer, log_dir=tmp_path / "logs").run()

    assert not outcome.ok
    assert outcome.error
    failed = [item for item in mailer.sent if "실패" in item["subject"]]
    assert failed, mailer.subjects()
    assert failed[0]["to"] == ["travislee@shinwon.com"]


@needs_ffmpeg
def test_waits_until_scheduled_time(media_server, tmp_path, mailer):
    """예약 시각이 오기 전에는 본 녹화를 시작하지 않는다."""
    import time
    from datetime import datetime, timedelta

    job = _make_job(f"{media_server}/live.mp4", tmp_path, duration="3s", preflight={"enabled": False})
    scheduled = datetime.now() + timedelta(seconds=3)

    started = time.monotonic()
    outcome = JobRunner(job, mailer, log_dir=tmp_path / "logs").run(scheduled_at=scheduled)
    assert outcome.ok, outcome.error
    assert outcome.started_at >= scheduled
    assert time.monotonic() - started >= 3
