"""작업 실행 흐름 조율.

  사전 점검(10초 샘플) -> 결과 메일 -> 예약 시각까지 대기 -> 본 녹화
  -> 결과물 검증 -> (선택) mp4 변환 -> 정상/실패 메일
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from .capture import capture, choose_backend, remux_to_mp4
from .errors import WebrecError
from .notify import (
    Mailer,
    completed_body,
    failed_body,
    preflight_body,
    started_body,
)
from .preflight import PreflightReport, run_preflight
from .verify import VerificationResult, verify_recording

log = logging.getLogger(__name__)

# 본 녹화는 중간에 끊겨 이어붙였을 수 있으므로 사전 점검보다 기준을 완화한다.
FINAL_MIN_FILL_RATIO = 0.5


@dataclass
class JobOutcome:
    """작업 1회 실행 결과."""

    job_name: str
    stage: str = "준비"
    ok: bool = False
    started_at: datetime = field(default_factory=datetime.now)
    finished_at: datetime = field(default_factory=datetime.now)
    scheduled_at: datetime | None = None
    backend: str = ""
    output_path: Path | None = None
    attempts: int = 0
    error: str | None = None
    stderr_tail: str = ""
    warnings: list[str] = field(default_factory=list)
    verification: VerificationResult | None = None
    preflight: PreflightReport | None = None

    def to_dict(self) -> dict:
        return {
            "job": self.job_name,
            "ok": self.ok,
            "stage": self.stage,
            "backend": self.backend,
            "output_path": str(self.output_path) if self.output_path else None,
            "attempts": self.attempts,
            "error": self.error,
            "warnings": self.warnings,
            "started_at": self.started_at.isoformat(timespec="seconds"),
            "finished_at": self.finished_at.isoformat(timespec="seconds"),
            "scheduled_at": self.scheduled_at.isoformat(timespec="seconds") if self.scheduled_at else None,
            "preflight": self.preflight.to_dict() if self.preflight else None,
            "verification": self.verification.to_dict() if self.verification else None,
        }


class JobRunner:
    """하나의 Job 을 한 번 실행한다."""

    def __init__(
        self,
        job,
        mailer: Mailer,
        *,
        log_dir: Path | None = None,
        progress: Callable[[str, "JobOutcome"], None] | None = None,
    ):
        self.job = job
        self.mailer = mailer
        self.log_dir = Path(log_dir) if log_dir else None
        self._progress = progress

    def _stage(self, outcome: "JobOutcome", stage: str) -> None:
        """진행 단계를 기록하고(웹 UI 등에) 알린다."""
        outcome.stage = stage
        if self._progress is None:
            return
        try:
            self._progress(stage, outcome)
        except Exception:  # 진행 알림 실패가 녹화를 막으면 안 된다
            log.exception("진행 상태 알림 중 오류")

    # --------------------------------------------------------------- 알림
    def _notify(self, event: str, subject: str, body: str, *, attach: Path | None = None) -> None:
        if event not in self.job.notify.events:
            log.debug("[%s] '%s' 이벤트는 알림 대상이 아닙니다.", self.job.name, event)
            return
        attachments = [attach] if (attach and self.job.notify.attach_log) else []
        self.mailer.send(self.job.notify, subject, body, attachments=attachments)

    # --------------------------------------------------------------- 유틸
    def output_path(self, when: datetime) -> Path:
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in self.job.name)
        filename = f"{safe_name}_{when:%Y%m%d-%H%M%S}.{self.job.video.container}"
        return Path(self.job.output_dir).expanduser() / filename

    def ffmpeg_log_path(self, when: datetime) -> Path | None:
        if not self.log_dir:
            return None
        self.log_dir.mkdir(parents=True, exist_ok=True)
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in self.job.name)
        return self.log_dir / f"{safe_name}_{when:%Y%m%d-%H%M%S}.ffmpeg.log"

    @staticmethod
    def _sleep_until(target: datetime) -> None:
        while True:
            now = datetime.now(target.tzinfo) if target.tzinfo else datetime.now()
            remaining = (target - now).total_seconds()
            if remaining <= 0:
                return
            if remaining > 60:
                log.info("예약 시각까지 %.0f분 대기합니다. (%s)", remaining / 60, target.strftime("%H:%M:%S"))
            time.sleep(min(remaining, 30))

    # --------------------------------------------------------------- 실행
    def preflight(self, *, scheduled_at: datetime | None = None) -> PreflightReport:
        """샘플 녹화로 사전 점검하고 결과를 메일로 알린다."""
        report = run_preflight(self.job, log_file=self.ffmpeg_log_path(datetime.now()))
        if report.ok:
            self._notify(
                "preflight_passed",
                f"사전 점검 정상 - {self.job.name}",
                preflight_body(self.job, report, scheduled_at=scheduled_at),
            )
        else:
            self._notify(
                "preflight_failed",
                f"[주의] 사전 점검 실패 - {self.job.name}",
                preflight_body(self.job, report, scheduled_at=scheduled_at),
            )
        return report

    def run(self, *, scheduled_at: datetime | None = None, skip_preflight: bool = False) -> JobOutcome:
        """사전 점검 -> 대기 -> 본 녹화 -> 검증 -> 결과 통보."""
        job = self.job
        outcome = JobOutcome(job_name=job.name, scheduled_at=scheduled_at)
        outcome.backend, _ = choose_backend(job.url, job.backend)

        # 1) 사전 점검
        if job.preflight.enabled and not skip_preflight:
            self._stage(outcome, "사전 점검")
            try:
                outcome.preflight = self.preflight(scheduled_at=scheduled_at)
            except Exception as exc:  # 점검 자체가 터져도 본 녹화는 시도한다
                log.exception("[%s] 사전 점검 실행 실패", job.name)
                outcome.warnings.append(f"사전 점검 실행 실패: {exc}")

            if outcome.preflight and not outcome.preflight.ok:
                if job.preflight.abort_on_failure:
                    self._stage(outcome, "사전 점검")
                    outcome.error = f"사전 점검 실패로 녹화를 취소했습니다: {outcome.preflight.error}"
                    outcome.finished_at = datetime.now()
                    self._notify(
                        "failed",
                        f"[실패] 녹화 취소 - {job.name}",
                        failed_body(job, outcome),
                        attach=self.ffmpeg_log_path(outcome.started_at),
                    )
                    return outcome
                outcome.warnings.append(
                    f"사전 점검 실패했지만 설정에 따라 녹화를 진행했습니다: {outcome.preflight.error}"
                )

        # 2) 예약 시각까지 대기
        if scheduled_at is not None:
            self._stage(outcome, "대기")
            self._sleep_until(scheduled_at)

        # 3) 본 녹화
        start_time = datetime.now()
        outcome.started_at = start_time
        out_path = self.output_path(start_time)
        ffmpeg_log = self.ffmpeg_log_path(start_time)
        self._stage(outcome, "녹화")

        self._notify(
            "started",
            f"녹화 시작 - {job.name}",
            started_body(job, scheduled_at=scheduled_at, output_path=out_path, backend=outcome.backend),
        )

        try:
            result = capture(job, out_path, job.duration, backend=outcome.backend, log_file=ffmpeg_log)
            outcome.output_path = result.path
            outcome.attempts = result.attempts
            outcome.stderr_tail = result.stderr_tail
            if result.attempts > 1:
                outcome.warnings.append(f"녹화 도중 {result.attempts - 1}회 끊겨 이어붙였습니다.")
        except WebrecError as exc:
            outcome.error = str(exc)
        except Exception as exc:
            log.exception("[%s] 녹화 중 예기치 못한 오류", job.name)
            outcome.error = f"{type(exc).__name__}: {exc}"

        # 4) 결과 검증
        if outcome.error is None and outcome.output_path:
            self._stage(outcome, "검증")
            try:
                outcome.verification = verify_recording(
                    outcome.output_path,
                    expected_duration=job.duration,
                    min_fill_ratio=FINAL_MIN_FILL_RATIO,
                    max_black_ratio=job.preflight.max_black_ratio,
                    require_audio=job.preflight.require_audio,
                )
                if not outcome.verification.ok:
                    outcome.error = "녹화 파일 검증 실패: " + "; ".join(
                        f"{c.name}({c.detail})" for c in outcome.verification.failures
                    )
            except Exception as exc:
                outcome.warnings.append(f"검증을 수행하지 못했습니다: {exc}")

        # 5) 후처리 (mp4 변환)
        if outcome.error is None and job.remux_mp4 and outcome.output_path:
            self._stage(outcome, "변환")
            try:
                outcome.output_path = remux_to_mp4(outcome.output_path)
            except Exception as exc:
                outcome.warnings.append(f"mp4 변환 실패(원본 유지): {exc}")

        outcome.finished_at = datetime.now()
        outcome.ok = outcome.error is None
        if outcome.ok:
            self._stage(outcome, "완료")

        if outcome.ok:
            log.info("[%s] 녹화 완료: %s", job.name, outcome.output_path)
            self._notify(
                "completed",
                f"녹화 완료 - {job.name}",
                completed_body(job, outcome),
                attach=ffmpeg_log,
            )
        else:
            log.error("[%s] 녹화 실패(%s): %s", job.name, outcome.stage, outcome.error)
            self._notify(
                "failed",
                f"[실패] 녹화 오류 - {job.name}",
                failed_body(job, outcome),
                attach=ffmpeg_log,
            )
        return outcome
