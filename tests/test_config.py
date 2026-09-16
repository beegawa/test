"""설정 파싱/검증 테스트."""

from __future__ import annotations

import os
from datetime import datetime

import pytest

from webrec.config import (
    build_config,
    expand_env,
    load_config,
    parse_datetime,
    parse_duration,
)
from webrec.errors import ConfigError


@pytest.mark.parametrize(
    "value,expected",
    [(3600, 3600), ("3600", 3600), ("90m", 5400), ("1h30m", 5400), ("1h", 3600), ("45s", 45), ("2h 15m", 8100)],
)
def test_parse_duration(value, expected):
    assert parse_duration(value) == expected


@pytest.mark.parametrize("value", ["", "abc", 0, -5, "0m", None])
def test_parse_duration_rejects_bad_values(value):
    with pytest.raises(ConfigError):
        parse_duration(value)


def test_parse_datetime_formats():
    assert parse_datetime("2026-09-20 21:00") == datetime(2026, 9, 20, 21, 0)
    assert parse_datetime("2026-09-20T21:00:30") == datetime(2026, 9, 20, 21, 0, 30)
    with pytest.raises(ConfigError):
        parse_datetime("내일 9시")


def test_expand_env(monkeypatch):
    monkeypatch.setenv("WEBREC_TEST_TOKEN", "secret")
    assert expand_env("${WEBREC_TEST_TOKEN}") == "secret"
    assert expand_env("${WEBREC_MISSING:-기본값}") == "기본값"
    assert expand_env({"a": ["${WEBREC_TEST_TOKEN}"]}) == {"a": ["secret"]}


def _minimal_raw(**overrides):
    job = {"name": "t", "url": "https://example.com/live", "duration": "10m", "start": "2030-01-01 10:00"}
    job.update(overrides)
    return {"jobs": [job]}


def test_defaults_are_merged():
    raw = {
        "defaults": {"backend": "browser", "output_dir": "/tmp/rec", "preflight": {"duration": 15}},
        "jobs": [
            {"name": "a", "url": "https://example.com/a", "duration": "5m", "start": "2030-01-01 10:00"},
            {"name": "b", "url": "https://example.com/b", "duration": "5m", "cron": "0 9 * * *",
             "preflight": {"duration": 20}},
        ],
    }
    config = build_config(raw)
    assert config.jobs[0].backend == "browser"
    assert str(config.jobs[0].output_dir) == "/tmp/rec"
    assert config.jobs[0].preflight.duration == 15     # defaults 상속
    assert config.jobs[1].preflight.duration == 20     # 작업별 재정의


def test_job_requires_url_and_time():
    with pytest.raises(ConfigError, match="url"):
        build_config({"jobs": [{"name": "x", "duration": "5m", "start": "2030-01-01 10:00"}]})
    with pytest.raises(ConfigError, match="start"):
        build_config({"jobs": [{"name": "x", "url": "https://e.com", "duration": "5m"}]})
    with pytest.raises(ConfigError, match="duration"):
        build_config({"jobs": [{"name": "x", "url": "https://e.com", "start": "2030-01-01 10:00"}]})


def test_start_and_cron_are_exclusive():
    with pytest.raises(ConfigError, match="동시에"):
        build_config(_minimal_raw(cron="0 9 * * *"))


def test_invalid_url_scheme():
    with pytest.raises(ConfigError, match="http"):
        build_config({"jobs": [{"url": "zoommtg://zoom.us/join", "duration": "5m", "start": "2030-01-01 10:00"}]})


def test_duplicate_job_names():
    raw = {"jobs": [
        {"name": "same", "url": "https://e.com/1", "duration": "5m", "start": "2030-01-01 10:00"},
        {"name": "same", "url": "https://e.com/2", "duration": "5m", "start": "2030-01-01 11:00"},
    ]}
    with pytest.raises(ConfigError, match="중복"):
        build_config(raw)


def test_unknown_notify_event():
    with pytest.raises(ConfigError, match="알 수 없는 이벤트"):
        build_config(_minimal_raw(notify={"to": "a@b.com", "on": ["보내줘"]}))


def test_notify_defaults_to_requested_address():
    config = build_config(_minimal_raw())
    assert config.jobs[0].notify.to == ["travislee@shinwon.com"]


def test_notify_accepts_comma_separated():
    config = build_config(_minimal_raw(notify={"to": "a@b.com, c@d.com"}))
    assert config.jobs[0].notify.to == ["a@b.com", "c@d.com"]


def test_preflight_defaults_to_ten_seconds():
    config = build_config(_minimal_raw())
    assert config.jobs[0].preflight.enabled is True
    assert config.jobs[0].preflight.duration == 10


def test_preflight_minimum_duration():
    with pytest.raises(ConfigError, match="최소 3초"):
        build_config(_minimal_raw(preflight={"duration": 1}))


def test_invalid_cron_is_rejected():
    with pytest.raises(ConfigError, match="cron"):
        build_config({"jobs": [{"url": "https://e.com", "duration": "5m", "cron": "매일 9시"}]})


def test_invalid_timezone():
    with pytest.raises(ConfigError, match="타임존"):
        build_config(_minimal_raw(timezone="Mars/Olympus"))


def test_load_config_from_file(tmp_path, monkeypatch):
    monkeypatch.setenv("SMTP_PASS_TEST", "pw123")
    path = tmp_path / "webrec.yaml"
    path.write_text(
        "smtp:\n"
        "  host: smtp.example.com\n"
        "  username: bot@example.com\n"
        "  password: ${SMTP_PASS_TEST}\n"
        "jobs:\n"
        "  - name: 야간뉴스\n"
        "    url: https://www.youtube.com/watch?v=abc\n"
        "    start: '2030-03-01 21:00'\n"
        "    duration: 1h\n",
        encoding="utf-8",
    )
    config = load_config(path)
    assert config.smtp.password == "pw123"
    assert config.smtp.sender == "bot@example.com"   # from 생략 시 username 사용
    assert config.jobs[0].name == "야간뉴스"
    assert config.jobs[0].duration == 3600


def test_example_config_is_valid(monkeypatch):
    monkeypatch.setenv("SMTP_USER", "u@example.com")
    monkeypatch.setenv("SMTP_PASS", "pw")
    config = load_config(os.path.join(os.path.dirname(__file__), "..", "config.example.yaml"))
    assert len(config.jobs) == 3
    assert config.jobs[0].notify.to == ["travislee@shinwon.com"]
