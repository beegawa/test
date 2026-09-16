"""메일 알림 테스트 - 실제 SMTP 대신 가짜 서버를 쓴다."""

from __future__ import annotations

import smtplib
from datetime import datetime
from pathlib import Path

import pytest

from webrec.config import NotifyConfig, SmtpConfig, build_config
from webrec.errors import NotifyError
from webrec.notify import Mailer, completed_body, failed_body, preflight_body
from webrec.preflight import PreflightReport
from webrec.runner import JobOutcome


class FakeSMTP:
    """smtplib.SMTP 대역."""

    sent: list = []
    logged_in: list = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port = host, port
        self.started_tls = False

    def ehlo(self):
        return 250, b"ok"

    def starttls(self):
        self.started_tls = True

    def login(self, user, password):
        FakeSMTP.logged_in.append((user, password))

    def send_message(self, message, from_addr=None, to_addrs=None):
        FakeSMTP.sent.append({"message": message, "from": from_addr, "to": to_addrs})

    def quit(self):
        pass

    def close(self):
        pass


@pytest.fixture(autouse=True)
def reset_fake():
    FakeSMTP.sent = []
    FakeSMTP.logged_in = []


@pytest.fixture
def smtp_cfg():
    return SmtpConfig(host="smtp.test", port=587, username="bot@test", password="pw", sender="bot@test")


def _job(**overrides):
    raw = {"name": "회의녹화", "url": "https://zoom.us/j/1", "duration": "30m", "start": "2030-01-01 10:00"}
    raw.update(overrides)
    return build_config({"jobs": [raw]}).jobs[0]


def test_send_delivers_to_configured_address(monkeypatch, smtp_cfg):
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    mailer = Mailer(smtp_cfg)
    assert mailer.send(NotifyConfig(), "제목", "본문") is True

    assert len(FakeSMTP.sent) == 1
    sent = FakeSMTP.sent[0]
    assert sent["to"] == ["travislee@shinwon.com"]
    assert sent["message"]["Subject"] == "[webrec] 제목"
    assert FakeSMTP.logged_in == [("bot@test", "pw")]


def test_send_attaches_log_file(monkeypatch, smtp_cfg, tmp_path: Path):
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    log_file = tmp_path / "run.log"
    log_file.write_text("ffmpeg 로그 내용", encoding="utf-8")

    Mailer(smtp_cfg).send(NotifyConfig(), "제목", "본문", attachments=[log_file])
    attachments = [p.get_filename() for p in FakeSMTP.sent[0]["message"].iter_attachments()]
    assert attachments == ["run.log"]


def test_send_survives_smtp_failure(monkeypatch, smtp_cfg):
    """메일이 실패해도 예외로 녹화 작업을 죽이지 않는다."""

    def boom(*args, **kwargs):
        raise smtplib.SMTPAuthenticationError(535, b"bad credentials")

    monkeypatch.setattr(smtplib, "SMTP", boom)
    assert Mailer(smtp_cfg).send(NotifyConfig(), "제목", "본문") is False


def test_dry_run_when_smtp_not_configured():
    mailer = Mailer(SmtpConfig())
    assert mailer.dry_run is True
    assert mailer.send(NotifyConfig(), "제목", "본문") is False
    with pytest.raises(NotifyError, match="SMTP"):
        mailer.send_test(NotifyConfig())


def test_ssl_mode_uses_smtp_ssl(monkeypatch):
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    cfg = SmtpConfig(host="smtp.test", port=465, username="bot@test", password="pw", ssl=True)
    assert Mailer(cfg).send(NotifyConfig(), "제목", "본문") is True
    assert len(FakeSMTP.sent) == 1


# ------------------------------------------------------------------- 본문
def test_preflight_body_mentions_failure_hints():
    job = _job()
    report = PreflightReport(
        job_name=job.name, url=job.url, backend="browser", duration=10, ok=False,
        started_at=datetime.now(), error="화면 내용: 검은 화면 비율 100%",
    )
    body = preflight_body(job, report, scheduled_at=datetime(2030, 1, 1, 10, 0))
    assert "사전 점검" in body
    assert "검은 화면" in body
    assert "2030-01-01 10:00:00" in body
    assert "확인해 보세요" in body


def test_completed_body_has_file_and_size(tmp_path):
    job = _job()
    outcome = JobOutcome(job_name=job.name, ok=True, output_path=tmp_path / "out.mkv", attempts=1, backend="stream")
    from webrec.verify import Check, VerificationResult

    outcome.verification = VerificationResult(
        path=tmp_path / "out.mkv",
        checks=[Check("비디오 스트림", True, "h264 1280x720 @ 30.0fps")],
        metrics={"size_bytes": 5 * 1024 * 1024, "duration_sec": 1800, "width": 1280, "height": 720},
    )
    body = completed_body(job, outcome)
    assert "정상적으로 끝났습니다" in body
    assert "5.0 MB" in body
    assert "1280x720" in body


def test_failed_body_includes_error_and_log_tail():
    job = _job()
    outcome = JobOutcome(
        job_name=job.name, ok=False, stage="녹화", error="스트림 연결 실패",
        stderr_tail="Connection refused", backend="stream",
    )
    body = failed_body(job, outcome)
    assert "문제가 발생했습니다" in body
    assert "스트림 연결 실패" in body
    assert "Connection refused" in body
