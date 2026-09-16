"""웹 예약 저장소 테스트."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from webrec.errors import ConfigError
from webrec.store import STATUS_DISABLED, STATUS_DONE, STATUS_SCHEDULED, JobStore


def _spec(**overrides):
    spec = {"name": "테스트", "url": "https://example.com/live", "duration": "30m",
            "start": "2030-01-01 21:00"}
    spec.update(overrides)
    return spec


def test_add_and_list(tmp_path):
    store = JobStore(tmp_path / "jobs.json")
    record = store.add(_spec())

    assert record.id and len(record.id) == 8
    assert record.status == STATUS_SCHEDULED
    assert [r.id for r in store.list()] == [record.id]
    assert store.get(record.id).name == "테스트"


def test_invalid_spec_is_rejected(tmp_path):
    store = JobStore(tmp_path / "jobs.json")
    with pytest.raises(ConfigError):
        store.add(_spec(url="zoommtg://not-http"))
    with pytest.raises(ConfigError):
        store.add(_spec(duration="언젠가"))
    assert store.list() == []


def test_survives_restart(tmp_path):
    path = tmp_path / "jobs.json"
    record = JobStore(path).add(_spec(name="재시작테스트"))

    reopened = JobStore(path)
    assert reopened.get(record.id).name == "재시작테스트"
    assert reopened.get(record.id).spec["duration"] == "30m"


def test_file_is_owner_only(tmp_path):
    """메일 비밀번호가 들어갈 수 있으므로 본인만 읽을 수 있어야 한다."""
    path = tmp_path / "jobs.json"
    store = JobStore(path)
    store.update_settings({"smtp": {"host": "smtp.test", "password": "secret"}})
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_delete(tmp_path):
    store = JobStore(tmp_path / "jobs.json")
    record = store.add(_spec())
    assert store.delete(record.id) is True
    assert store.delete(record.id) is False
    assert store.list() == []


def test_pause_and_resume(tmp_path):
    store = JobStore(tmp_path / "jobs.json")
    record = store.add(_spec())

    store.set_enabled(record.id, False)
    assert store.get(record.id).enabled is False
    assert store.get(record.id).status == STATUS_DISABLED

    store.set_enabled(record.id, True)
    assert store.get(record.id).enabled is True
    assert store.get(record.id).status == STATUS_SCHEDULED


def test_runs_are_capped_and_newest_first(tmp_path):
    store = JobStore(tmp_path / "jobs.json")
    record = store.add(_spec())
    for i in range(25):
        store.add_run(record.id, {"kind": "녹화", "ok": True, "at": f"2030-01-{i + 1:02d}"})

    runs = store.get(record.id).runs
    assert len(runs) == 20                      # 최근 20개만 보관
    assert runs[0]["at"] == "2030-01-25"        # 최신이 앞


def test_update_status(tmp_path):
    store = JobStore(tmp_path / "jobs.json")
    record = store.add(_spec())
    store.update(record.id, status=STATUS_DONE, message="끝")
    assert store.get(record.id).status == STATUS_DONE
    assert store.get(record.id).message == "끝"
    assert store.update("없는id", status=STATUS_DONE) is None


def test_settings_roundtrip(tmp_path):
    path = tmp_path / "jobs.json"
    store = JobStore(path)
    store.update_settings({"smtp": {"host": "smtp.test", "port": 587}, "notify_to": "a@b.com"})

    assert JobStore(path).settings["notify_to"] == "a@b.com"
    assert JobStore(path).settings["smtp"]["host"] == "smtp.test"


def test_corrupt_file_does_not_crash(tmp_path):
    path = tmp_path / "jobs.json"
    path.write_text("{깨진 파일", encoding="utf-8")
    store = JobStore(path)                      # 예외 없이 빈 상태로 시작
    assert store.list() == []
    assert store.add(_spec()) is not None


def test_record_builds_job(tmp_path):
    store = JobStore(tmp_path / "jobs.json")
    record = store.add(_spec(backend="browser", duration="1h30m"))
    job = record.to_job()
    assert job.duration == 5400
    assert job.backend == "browser"
    assert job.notify.to == ["travislee@shinwon.com"]
