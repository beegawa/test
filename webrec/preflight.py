"""본 녹화 전 샘플링 점검.

실제 예약 시간에 '녹화는 돌았는데 파일이 검은 화면' 같은 사고를 막기 위해,
시작 몇 분 전에 같은 방식으로 10초짜리 샘플을 떠 보고 검증한다.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .capture import capture, choose_backend
from .errors import CaptureError, WebrecError
from .sites import check_reachable
from .verify import Check, VerificationResult, verify_recording

log = logging.getLogger(__name__)


@dataclass
class PreflightReport:
    """샘플링 점검 결과."""

    job_name: str
    url: str
    backend: str
    duration: int
    ok: bool
    started_at: datetime
    elapsed: float = 0.0
    sample_path: Path | None = None
    checks: list[Check] = field(default_factory=list)   # 캡처 전에 확인한 항목들
    verification: VerificationResult | None = None
    error: str | None = None
    notes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"캡처 방식  : {self.backend}",
            f"샘플 길이  : {self.duration}초",
            f"결과       : {'정상' if self.ok else '실패'}",
        ]
        if self.error:
            lines.append(f"오류       : {self.error}")
        if self.checks or self.verification:
            lines.append("")
            lines.append("[검사 항목]")
        for check in self.checks:
            lines.append(f"{check.symbol:4} | {check.name}: {check.detail}")
        if self.verification:
            lines.append(self.verification.summary())
        if self.notes:
            lines.append("")
            lines.extend(f"- {note}" for note in self.notes)
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "job": self.job_name,
            "url": self.url,
            "backend": self.backend,
            "duration": self.duration,
            "ok": self.ok,
            "elapsed": round(self.elapsed, 1),
            "sample_path": str(self.sample_path) if self.sample_path else None,
            "error": self.error,
            "checks": [
                {"name": c.name, "ok": c.ok, "detail": c.detail, "fatal": c.fatal} for c in self.checks
            ],
            "verification": self.verification.to_dict() if self.verification else None,
        }


def run_preflight(job, *, workdir: Path | None = None, log_file: Path | None = None) -> PreflightReport:
    """job 과 동일한 조건으로 짧은 샘플을 녹화하고 검증한다."""
    cfg = job.preflight
    backend, _ = choose_backend(job.url, job.backend)
    started = time.monotonic()
    workdir = workdir or (Path(job.output_dir) / ".preflight")
    workdir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    sample_path = workdir / f"{job.name}_preflight_{stamp}.{job.video.container}"

    report = PreflightReport(
        job_name=job.name,
        url=job.url,
        backend=backend,
        duration=cfg.duration,
        ok=False,
        started_at=datetime.now(),
    )

    # 1) 주소에 실제로 접속되는지 먼저 확인한다.
    #    (브라우저 캡처는 페이지가 안 열려도 에러 화면이 '정상 녹화'처럼 보인다)
    level, detail = check_reachable(job.url)
    report.checks.append(
        Check("접속 확인", level == "ok", detail, fatal=(level == "fail"))
    )
    if level == "fail":
        report.error = f"주소에 접속할 수 없습니다 - {detail}"
        report.elapsed = time.monotonic() - started
        log.error("[%s] 사전 점검 실패: %s", job.name, report.error)
        return report
    if level == "warn":
        report.notes.append(f"경고: 접속 확인 - {detail}")

    log.info("[%s] 사전 점검: %d초 샘플 녹화 시작", job.name, cfg.duration)
    try:
        result = capture(
            job,
            sample_path,
            cfg.duration,
            backend=backend,
            log_file=log_file,
            max_retries=1,  # 점검 단계에서는 재시도를 최소화한다
        )
        report.sample_path = result.path
        report.verification = verify_recording(
            result.path,
            expected_duration=cfg.duration,
            min_fill_ratio=cfg.min_fill_ratio,
            max_black_ratio=cfg.max_black_ratio,
            require_audio=cfg.require_audio,
        )
        report.ok = report.verification.ok and all(c.ok for c in report.checks if c.fatal)

        for warning in report.verification.warnings:
            report.notes.append(f"경고: {warning.name} - {warning.detail}")
        if not report.ok:
            report.error = "; ".join(f"{c.name}: {c.detail}" for c in report.verification.failures)

    except CaptureError as exc:
        report.error = str(exc)
    except WebrecError as exc:
        report.error = str(exc)
    except Exception as exc:  # 예상 못 한 오류도 메일로 알려야 한다
        log.exception("[%s] 사전 점검 중 예기치 못한 오류", job.name)
        report.error = f"{type(exc).__name__}: {exc}"
    finally:
        report.elapsed = time.monotonic() - started
        if report.sample_path and not cfg.keep_sample:
            try:
                Path(report.sample_path).unlink(missing_ok=True)
            except OSError:  # pragma: no cover
                pass

    log.info("[%s] 사전 점검 결과: %s", job.name, "정상" if report.ok else f"실패 ({report.error})")
    return report
