"""메일 알림.

작업 시작 전 점검 결과, 정상 종료, 오류 발생을 지정된 주소로 보낸다.
SMTP 설정이 없으면 메일 내용을 로그로만 남기고 프로그램은 계속 진행한다.
"""

from __future__ import annotations

import logging
import smtplib
import socket
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr, formatdate
from pathlib import Path

from .config import NotifyConfig, SmtpConfig
from .errors import NotifyError

log = logging.getLogger(__name__)

_LOG_TAIL_BYTES = 200 * 1024  # 첨부 로그는 마지막 200KiB 만


class Mailer:
    """SMTP 발송기. dry_run=True 면 실제로 보내지 않고 로그만 남긴다."""

    def __init__(self, smtp: SmtpConfig, *, dry_run: bool = False):
        self.smtp = smtp
        self.dry_run = dry_run or not smtp.configured

    def send(
        self,
        notify: NotifyConfig,
        subject: str,
        body: str,
        *,
        attachments: list[Path] | None = None,
    ) -> bool:
        """메일 발송. 성공하면 True.

        메일 실패 때문에 녹화 작업이 죽으면 안 되므로 예외 대신 False 를 돌려준다.
        """
        full_subject = f"{notify.subject_prefix} {subject}".strip()
        recipients = list(notify.to)

        if self.dry_run:
            log.warning(
                "SMTP 설정이 없어 메일을 보내지 않습니다. 수신자=%s\n제목: %s\n%s",
                recipients, full_subject, body,
            )
            return False

        message = self._build(full_subject, body, recipients, attachments or [])
        try:
            self._deliver(message, recipients)
            log.info("메일 발송 완료 -> %s (%s)", ", ".join(recipients), full_subject)
            return True
        except (smtplib.SMTPException, OSError, socket.error) as exc:
            log.error("메일 발송 실패: %s", exc)
            return False

    # ------------------------------------------------------------------ 내부
    def _build(self, subject: str, body: str, recipients: list[str], attachments: list[Path]) -> EmailMessage:
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = formataddr(("webrec", self.smtp.sender or self.smtp.username))
        message["To"] = ", ".join(recipients)
        message["Date"] = formatdate(localtime=True)
        message.set_content(body)

        for path in attachments:
            try:
                path = Path(path)
                if not path.is_file():
                    continue
                data = _tail_bytes(path, _LOG_TAIL_BYTES)
                message.add_attachment(
                    data, maintype="text", subtype="plain", filename=path.name
                )
            except OSError as exc:  # pragma: no cover
                log.warning("첨부 실패(%s): %s", path, exc)
        return message

    def _deliver(self, message: EmailMessage, recipients: list[str]) -> None:
        smtp = self.smtp
        if smtp.ssl:
            server = smtplib.SMTP_SSL(smtp.host, smtp.port, timeout=smtp.timeout)
        else:
            server = smtplib.SMTP(smtp.host, smtp.port, timeout=smtp.timeout)
        try:
            server.ehlo()
            if smtp.starttls and not smtp.ssl:
                server.starttls()
                server.ehlo()
            if smtp.username:
                server.login(smtp.username, smtp.password)
            server.send_message(message, from_addr=smtp.sender or smtp.username, to_addrs=recipients)
        finally:
            try:
                server.quit()
            except smtplib.SMTPException:  # pragma: no cover
                server.close()

    def send_test(self, notify: NotifyConfig) -> bool:
        """설정 확인용 테스트 메일."""
        if self.dry_run:
            raise NotifyError(
                "SMTP 설정이 비어 있습니다. smtp.host / SMTP_HOST 등 환경변수를 설정하세요."
            )
        return self.send(
            notify,
            "메일 설정 테스트",
            "webrec 메일 설정이 정상입니다.\n"
            f"보낸 시각: {datetime.now():%Y-%m-%d %H:%M:%S}\n"
            f"호스트: {socket.gethostname()}\n",
        )


def _tail_bytes(path: Path, limit: int) -> bytes:
    size = path.stat().st_size
    with path.open("rb") as handle:
        if size > limit:
            handle.seek(size - limit)
            return "...(앞부분 생략)...\n".encode("utf-8") + handle.read()
        return handle.read()


# ------------------------------------------------------------------ 본문 작성
def _line(label: str, value) -> str:
    return f"{label:<12}: {value}"


def preflight_body(job, report, *, scheduled_at: datetime | None = None) -> str:
    lines = [
        "예약 녹화 사전 점검 결과입니다.",
        "",
        _line("작업", job.name),
        _line("주소", job.url),
        _line("예정 시각", scheduled_at.strftime("%Y-%m-%d %H:%M:%S") if scheduled_at else "-"),
        _line("녹화 길이", f"{job.duration}초 ({job.duration / 60:.0f}분)"),
        "",
        report.summary(),
    ]
    if not report.ok:
        lines += [
            "",
            "[확인해 보세요]",
            "- 라이브가 아직 시작되지 않았을 수 있습니다.",
            "- 로그인/암호가 필요한 주소라면 backend: browser 와 browser.passcode 설정이 필요합니다.",
            "- Zoom 은 회의 시작 전에는 대기실 화면만 캡처됩니다.",
        ]
    return "\n".join(lines)


def started_body(job, *, scheduled_at: datetime | None, output_path: Path, backend: str) -> str:
    return "\n".join([
        "예약된 녹화를 시작했습니다.",
        "",
        _line("작업", job.name),
        _line("주소", job.url),
        _line("시작 시각", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        _line("예정 시각", scheduled_at.strftime("%Y-%m-%d %H:%M:%S") if scheduled_at else "-"),
        _line("녹화 길이", f"{job.duration}초 ({job.duration / 60:.0f}분)"),
        _line("캡처 방식", backend),
        _line("저장 위치", str(output_path)),
    ])


def completed_body(job, outcome) -> str:
    verification = outcome.verification
    metrics = verification.metrics if verification else {}
    size_mb = (metrics.get("size_bytes") or 0) / (1024 * 1024)
    lines = [
        "예약 녹화가 정상적으로 끝났습니다.",
        "",
        _line("작업", job.name),
        _line("주소", job.url),
        _line("저장 파일", str(outcome.output_path)),
        _line("파일 크기", f"{size_mb:.1f} MB"),
        _line("녹화 길이", f"{metrics.get('duration_sec') or 0:.0f}초 (요청 {job.duration}초)"),
        _line("해상도", f"{metrics.get('width')}x{metrics.get('height')}"),
        _line("캡처 방식", outcome.backend),
        _line("재시도", f"{outcome.attempts - 1}회" if outcome.attempts else "0회"),
        _line("시작/종료", f"{outcome.started_at:%Y-%m-%d %H:%M:%S} ~ {outcome.finished_at:%H:%M:%S}"),
    ]
    if verification:
        lines += ["", "[검사 항목]", verification.summary()]
    if outcome.warnings:
        lines += ["", "[참고]"] + [f"- {w}" for w in outcome.warnings]
    return "\n".join(lines)


def failed_body(job, outcome) -> str:
    lines = [
        "예약 녹화 중 문제가 발생했습니다.",
        "",
        _line("작업", job.name),
        _line("주소", job.url),
        _line("단계", outcome.stage),
        _line("오류", outcome.error or "-"),
        _line("시작 시각", f"{outcome.started_at:%Y-%m-%d %H:%M:%S}"),
        _line("경과", f"{(outcome.finished_at - outcome.started_at).total_seconds():.0f}초"),
    ]
    if outcome.output_path:
        lines.append(_line("남은 파일", str(outcome.output_path)))
    if outcome.verification:
        lines += ["", "[검사 항목]", outcome.verification.summary()]
    if outcome.stderr_tail:
        lines += ["", "[ffmpeg 로그 끝부분]", outcome.stderr_tail[-2000:]]
    return "\n".join(lines)
