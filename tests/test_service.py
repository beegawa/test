"""예약 데몬(Scheduler)과 상태 저장 테스트."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from webrec.config import build_config
from webrec.runner import JobOutcome
from webrec.service import JobState, Scheduler


def _config(tmp_path: Path, **job_overrides):
    raw = {
        "log_dir": str(tmp_path / "logs"),
        "state_dir": str(tmp_path / "state"),
        "jobs": [{
            "name": "야간뉴스",
            "url": "https://example.com/live",
            "duration": "10m",
            "start": "2030-01-01 21:00",
            "output_dir": str(tmp_path / "rec"),
            **job_overrides,
        }],
    }
    return build_config(raw)


def test_state_roundtrip(tmp_path):
    state = JobState(tmp_path / "state")
    outcome = JobOutcome(
        job_name="야간뉴스", ok=True, output_path=tmp_path / "a.mkv",
        scheduled_at=datetime(2030, 1, 1, 21, 0),
    )
    state.record("야간뉴스", outcome)

    saved = state.load("야간뉴스")
    assert saved["last_ok"] is True
    assert saved["last_scheduled"] == "2030-01-01T21:00:00"
    assert saved["last_output"].endswith("a.mkv")


def test_state_handles_missing_and_corrupt_files(tmp_path):
    state = JobState(tmp_path / "state")
    assert state.load("없는작업") == {}
    (tmp_path / "state" / "깨진작업.json").write_text("{not json", encoding="utf-8")
    assert state.load("깨진작업") == {}


def test_dry_run_does_not_record(tmp_path, mailer):
    scheduler = Scheduler(_config(tmp_path), mailer=mailer, dry_run=True)
    assert scheduler.run() == 0
    assert mailer.sent == []
    assert not (tmp_path / "rec").exists()


def test_no_enabled_jobs_returns_error(tmp_path, mailer):
    config = _config(tmp_path, enabled=False)
    assert Scheduler(config, mailer=mailer).run() == 1


def test_stop_interrupts_waiting(tmp_path, mailer):
    """예약 시각을 기다리는 중에도 종료 신호를 받으면 곧바로 끝난다."""
    config = _config(tmp_path, start=(datetime.now() + timedelta(hours=5)).strftime("%Y-%m-%d %H:%M"))
    scheduler = Scheduler(config, mailer=mailer)

    thread = threading.Thread(target=scheduler.run, daemon=True)
    thread.start()
    time.sleep(0.5)
    scheduler.stop()
    thread.join(timeout=10)
    assert not thread.is_alive()


def test_expired_one_shot_job_exits_cleanly(tmp_path, mailer):
    """이미 지난 1회성 예약은 실행하지 않고 조용히 끝난다."""
    config = _config(tmp_path, start="2020-01-01 10:00")
    scheduler = Scheduler(config, mailer=mailer)
    assert scheduler.run() == 0
    assert mailer.sent == []


def test_job_failure_does_not_kill_daemon(tmp_path, mailer, monkeypatch):
    """한 작업이 터져도 데몬은 죽지 않고 정리된다."""
    config = _config(tmp_path, start=(datetime.now() + timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S"))
    config.jobs[0].preflight.enabled = False

    def boom(self, **kwargs):
        raise RuntimeError("의도적 오류")

    monkeypatch.setattr("webrec.runner.JobRunner.run", boom)
    scheduler = Scheduler(config, mailer=mailer)
    assert scheduler.run() == 0  # 예외가 밖으로 새지 않는다
