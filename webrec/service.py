"""예약 실행 데몬.

작업마다 스레드를 하나씩 두고
  '예약 시각 - 사전점검 리드타임' 까지 잠들었다가 -> 점검 -> 녹화
를 반복한다. 반복(cron) 작업은 끝나면 다음 시각을 다시 계산한다.
"""

from __future__ import annotations

import json
import logging
import signal
import threading
from datetime import datetime, timedelta
from pathlib import Path

from .config import Config, Job
from .notify import Mailer
from .runner import JobRunner
from .schedule import next_run

log = logging.getLogger(__name__)


class JobState:
    """마지막으로 처리한 예약 시각을 저장해 재시작 시 중복 실행을 막는다."""

    def __init__(self, state_dir: Path):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, job_name: str) -> Path:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in job_name)
        return self.state_dir / f"{safe}.json"

    def load(self, job_name: str) -> dict:
        path = self._path(job_name)
        if not path.is_file():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):  # pragma: no cover
            return {}

    def record(self, job_name: str, outcome) -> None:
        path = self._path(job_name)
        data = self.load(job_name)
        data.update(
            last_scheduled=outcome.scheduled_at.isoformat() if outcome.scheduled_at else None,
            last_finished=outcome.finished_at.isoformat(),
            last_ok=outcome.ok,
            last_output=str(outcome.output_path) if outcome.output_path else None,
            last_error=outcome.error,
        )
        try:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:  # pragma: no cover
            log.warning("상태 저장 실패(%s): %s", path, exc)


class Scheduler:
    """설정에 있는 모든 작업을 예약 실행한다."""

    def __init__(self, config: Config, *, mailer: Mailer | None = None, dry_run: bool = False):
        self.config = config
        self.mailer = mailer or Mailer(config.smtp)
        self.state = JobState(config.state_dir)
        self.dry_run = dry_run
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    def stop(self) -> None:
        log.info("종료 신호를 받았습니다. 진행 중인 녹화가 끝나면 종료합니다.")
        self._stop.set()

    def install_signal_handlers(self) -> None:
        def handler(signum, _frame):
            log.info("신호 수신: %s", signal.Signals(signum).name)
            self.stop()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, handler)
            except (ValueError, OSError):  # pragma: no cover - 메인 스레드가 아닐 때
                pass

    # ------------------------------------------------------------------ 루프
    def _wait_until(self, target: datetime) -> bool:
        """target 까지 대기. 중간에 종료 요청이 오면 False."""
        while not self._stop.is_set():
            now = datetime.now(target.tzinfo) if target.tzinfo else datetime.now()
            remaining = (target - now).total_seconds()
            if remaining <= 0:
                return True
            if self._stop.wait(min(remaining, 20)):
                return False
        return False

    def _job_loop(self, job: Job) -> None:
        runner = JobRunner(job, self.mailer, log_dir=self.config.log_dir)
        while not self._stop.is_set():
            scheduled = next_run(job)
            if scheduled is None:
                log.info("[%s] 남은 예약이 없습니다. 이 작업을 종료합니다.", job.name)
                return

            lead = job.preflight.lead_seconds if job.preflight.enabled else 0
            wake_at = scheduled - timedelta(seconds=lead)

            log.info(
                "[%s] 다음 녹화: %s (사전 점검 %s)",
                job.name,
                scheduled.strftime("%Y-%m-%d %H:%M:%S"),
                wake_at.strftime("%H:%M:%S") if lead else "생략",
            )

            if self.dry_run:
                log.info("[%s] dry-run: 실제 녹화는 하지 않습니다.", job.name)
                return

            if not self._wait_until(wake_at):
                return

            try:
                outcome = runner.run(scheduled_at=scheduled)
                self.state.record(job.name, outcome)
            except Exception:  # 한 작업의 실패가 데몬 전체를 죽이면 안 된다
                log.exception("[%s] 실행 중 치명적 오류", job.name)

            if job.start is not None:  # 1회성 작업
                log.info("[%s] 1회성 작업이 끝났습니다.", job.name)
                return

    def run(self) -> int:
        jobs = [job for job in self.config.jobs if job.enabled]
        if not jobs:
            log.error("실행할 작업이 없습니다. 설정 파일의 jobs 를 확인하세요.")
            return 1

        log.info("예약 대기 시작 - 작업 %d개", len(jobs))
        for job in jobs:
            thread = threading.Thread(target=self._job_loop, args=(job,), name=f"job:{job.name}", daemon=True)
            thread.start()
            self._threads.append(thread)

        try:
            while any(t.is_alive() for t in self._threads):
                if self._stop.wait(1):
                    break
        except KeyboardInterrupt:  # pragma: no cover
            self.stop()

        for thread in self._threads:
            thread.join(timeout=5)
        log.info("종료합니다.")
        return 0
