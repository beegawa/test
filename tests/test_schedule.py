"""예약 시각 계산 테스트."""

from __future__ import annotations

from datetime import datetime

import pytest

from webrec.config import build_config
from webrec.errors import ConfigError
from webrec.schedule import matches, next_cron_time, next_run, parse_cron, upcoming


def test_parse_cron_basic():
    parsed = parse_cron("30 9 * * *")
    assert parsed["minute"] == {30}
    assert parsed["hour"] == {9}
    assert len(parsed["day"]) == 31


def test_parse_cron_lists_ranges_steps():
    parsed = parse_cron("*/15 9-11 1,15 * mon-fri")
    assert parsed["minute"] == {0, 15, 30, 45}
    assert parsed["hour"] == {9, 10, 11}
    assert parsed["day"] == {1, 15}
    assert parsed["weekday"] == {1, 2, 3, 4, 5}


def test_parse_cron_weekday_names_and_sunday_seven():
    assert parse_cron("0 9 * * sun")["weekday"] == {0}
    assert parse_cron("0 9 * * 7")["weekday"] == {0}
    assert parse_cron("0 9 * * mon,wed")["weekday"] == {1, 3}


def test_parse_cron_aliases():
    assert parse_cron("@daily")["hour"] == {0}


@pytest.mark.parametrize("expr", ["", "0 9 * *", "61 9 * * *", "0 25 * * *", "abc 9 * * *", "9-5 9 * * *"])
def test_parse_cron_rejects_bad_expressions(expr):
    with pytest.raises(ConfigError):
        parse_cron(expr)


def test_next_cron_time_daily():
    after = datetime(2026, 9, 16, 8, 0)
    assert next_cron_time("0 9 * * *", after) == datetime(2026, 9, 16, 9, 0)
    after = datetime(2026, 9, 16, 9, 0)
    assert next_cron_time("0 9 * * *", after) == datetime(2026, 9, 17, 9, 0)


def test_next_cron_time_weekday_only():
    # 2026-09-16 은 수요일 -> 다음 월요일은 9/21
    after = datetime(2026, 9, 16, 12, 0)
    assert next_cron_time("0 9 * * mon", after) == datetime(2026, 9, 21, 9, 0)


def test_next_cron_time_day_or_weekday_union():
    # 표준 cron: 일/요일이 모두 지정되면 둘 중 하나만 맞아도 발동
    parsed = parse_cron("0 9 1 * mon")
    assert matches(parsed, datetime(2026, 9, 1, 9, 0))    # 1일(화)
    assert matches(parsed, datetime(2026, 9, 7, 9, 0))    # 월요일
    assert not matches(parsed, datetime(2026, 9, 8, 9, 0))


def test_next_cron_time_february_29():
    after = datetime(2026, 3, 1, 0, 0)
    assert next_cron_time("0 0 29 2 *", after) == datetime(2028, 2, 29, 0, 0)


def test_next_run_for_one_shot_job():
    config = build_config({"jobs": [{
        "name": "once", "url": "https://e.com", "duration": "10m", "start": "2030-05-05 20:00",
    }]})
    job = config.jobs[0]
    assert next_run(job, after=datetime(2030, 5, 5, 19, 0)) == datetime(2030, 5, 5, 20, 0)
    # 이미 지난 1회성 예약은 None
    assert next_run(job, after=datetime(2030, 5, 5, 21, 0)) is None


def test_next_run_respects_timezone():
    config = build_config({"jobs": [{
        "name": "tz", "url": "https://e.com", "duration": "10m",
        "cron": "0 9 * * *", "timezone": "Asia/Seoul",
    }]})
    when = next_run(config.jobs[0])
    assert when is not None
    assert when.hour == 9
    assert str(when.tzinfo) == "Asia/Seoul"


def test_upcoming_sorts_and_skips_disabled():
    config = build_config({"jobs": [
        {"name": "late", "url": "https://e.com/1", "duration": "10m", "start": "2030-01-02 10:00"},
        {"name": "early", "url": "https://e.com/2", "duration": "10m", "start": "2030-01-01 10:00"},
        {"name": "off", "url": "https://e.com/3", "duration": "10m", "start": "2030-01-01 09:00",
         "enabled": False},
    ]})
    rows = upcoming(config.jobs, after=datetime(2029, 1, 1))
    assert [job.name for job, _ in rows] == ["early", "late"]
