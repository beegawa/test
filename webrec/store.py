"""웹 UI 가 다루는 예약 목록 저장소.

설정 파일(webrec.yaml) 대신 사용자가 브라우저에서 추가/삭제하는 예약을
JSON 파일 하나에 보관한다. 여러 스레드(웹 요청 + 예약 실행)가 동시에
건드리므로 잠금과 원자적 쓰기를 사용한다.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import Job, build_config
from .errors import ConfigError

log = logging.getLogger(__name__)

# 예약 상태
STATUS_SCHEDULED = "예약됨"
STATUS_CHECKING = "점검중"
STATUS_WAITING = "대기중"
STATUS_RECORDING = "녹화중"
STATUS_VERIFYING = "검증중"
STATUS_DONE = "완료"
STATUS_FAILED = "실패"
STATUS_MISSED = "놓침"
STATUS_DISABLED = "중지됨"

ACTIVE_STATUSES = (STATUS_CHECKING, STATUS_WAITING, STATUS_RECORDING, STATUS_VERIFYING)

# 실행 단계 -> 화면에 보여줄 상태
STAGE_TO_STATUS = {
    "사전 점검": STATUS_CHECKING,
    "대기": STATUS_WAITING,
    "녹화": STATUS_RECORDING,
    "검증": STATUS_VERIFYING,
    "변환": STATUS_VERIFYING,
    "완료": STATUS_DONE,
}

MAX_RUNS_KEPT = 20


@dataclass
class JobRecord:
    """웹에서 등록한 예약 하나."""

    id: str
    spec: dict                              # webrec 설정 형식의 작업 정의
    status: str = STATUS_SCHEDULED
    created_at: str = ""
    message: str = ""                       # 화면에 띄울 짧은 안내/오류
    started_at: str | None = None           # 현재 녹화 시작 시각
    duration_sec: int | None = None         # 현재 녹화의 실제 길이(지각 시작 시 줄어듦)
    runs: list[dict] = field(default_factory=list)

    @property
    def name(self) -> str:
        return str(self.spec.get("name") or self.id)

    @property
    def enabled(self) -> bool:
        return bool(self.spec.get("enabled", True))

    def to_job(self) -> Job:
        """저장된 정의를 실제 Job 객체로 만든다 (검증 포함)."""
        return build_config({"jobs": [dict(self.spec)]}, require_schedule=False).jobs[0]

    def to_dict(self) -> dict:
        return asdict(self)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class JobStore:
    """예약 목록과 설정을 JSON 파일에 보관."""

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._jobs: dict[str, JobRecord] = {}
        self._settings: dict[str, Any] = {}
        self._load()

    # ------------------------------------------------------------- 파일 입출력
    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.error("예약 파일을 읽지 못했습니다(%s): %s", self.path, exc)
            return
        for item in raw.get("jobs", []):
            try:
                record = JobRecord(**item)
            except TypeError as exc:  # 형식이 바뀐 옛 파일
                log.warning("예약 항목을 건너뜁니다: %s", exc)
                continue
            self._jobs[record.id] = record
        self._settings = raw.get("settings", {})

    def _save_locked(self) -> None:
        data = {
            "jobs": [record.to_dict() for record in self._jobs.values()],
            "settings": self._settings,
        }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)
        try:  # 메일 비밀번호가 들어갈 수 있으므로 본인만 읽게 한다
            os.chmod(self.path, 0o600)
        except OSError:  # pragma: no cover - 윈도우 등
            pass

    def save(self) -> None:
        with self._lock:
            self._save_locked()

    # ----------------------------------------------------------------- 예약
    def list(self) -> list[JobRecord]:
        with self._lock:
            return list(self._jobs.values())

    def get(self, job_id: str) -> JobRecord | None:
        with self._lock:
            return self._jobs.get(job_id)

    def add(self, spec: dict) -> JobRecord:
        """예약 추가. 정의가 잘못되면 ConfigError."""
        spec = dict(spec)
        record = JobRecord(id=uuid.uuid4().hex[:8], spec=spec, created_at=_now())
        record.to_job()  # 여기서 검증 (잘못되면 ConfigError)
        with self._lock:
            if not spec.get("name"):
                spec["name"] = f"녹화-{record.id}"
            self._jobs[record.id] = record
            self._save_locked()
        log.info("예약 추가: %s (%s)", record.name, record.id)
        return record

    def delete(self, job_id: str) -> bool:
        with self._lock:
            removed = self._jobs.pop(job_id, None)
            if removed:
                self._save_locked()
        return removed is not None

    def update(self, job_id: str, **fields) -> JobRecord | None:
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None:
                return None
            for key, value in fields.items():
                setattr(record, key, value)
            self._save_locked()
            return record

    def set_enabled(self, job_id: str, enabled: bool) -> JobRecord | None:
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None:
                return None
            record.spec["enabled"] = enabled
            if not enabled:
                record.status = STATUS_DISABLED
            elif record.status == STATUS_DISABLED:
                record.status = STATUS_SCHEDULED
            self._save_locked()
            return record

    def add_run(self, job_id: str, run: dict) -> None:
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None:
                return
            record.runs.insert(0, run)
            del record.runs[MAX_RUNS_KEPT:]
            self._save_locked()

    # ----------------------------------------------------------------- 설정
    @property
    def settings(self) -> dict:
        with self._lock:
            return json.loads(json.dumps(self._settings))  # 복사본

    def update_settings(self, values: dict) -> dict:
        with self._lock:
            self._settings.update(values)
            self._save_locked()
            return json.loads(json.dumps(self._settings))
