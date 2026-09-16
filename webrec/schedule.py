"""예약 시각 계산.

외부 의존성 없이 5필드 cron('분 시 일 월 요일')을 해석한다.
지원: `*`, `1,2,3`, `1-5`, `*/15`, `1-30/5`, 요일 이름(mon..sun), 월 이름(jan..dec).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable

from .errors import ConfigError

_FIELD_RANGES = {
    "minute": (0, 59),
    "hour": (0, 23),
    "day": (1, 31),
    "month": (1, 12),
    "weekday": (0, 6),  # 0=일요일
}
_FIELD_ORDER = ("minute", "hour", "day", "month", "weekday")

_WEEKDAY_NAMES = {
    "sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6,
}
_MONTH_NAMES = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

_ALIASES = {
    "@hourly": "0 * * * *",
    "@daily": "0 0 * * *",
    "@midnight": "0 0 * * *",
    "@weekly": "0 0 * * 0",
    "@monthly": "0 0 1 * *",
    "@yearly": "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
}

# 무한 루프 방지: 4년 이상 앞은 보지 않는다.
_MAX_LOOKAHEAD_DAYS = 366 * 4


def _normalize_token(token: str, field: str) -> str:
    lowered = token.lower()
    if field == "weekday":
        for name, num in _WEEKDAY_NAMES.items():
            lowered = lowered.replace(name, str(num))
        lowered = lowered.replace("7", "0") if lowered == "7" else lowered
    elif field == "month":
        for name, num in _MONTH_NAMES.items():
            lowered = lowered.replace(name, str(num))
    return lowered


def _parse_field(expr: str, field: str) -> set[int]:
    low, high = _FIELD_RANGES[field]
    values: set[int] = set()

    for part in expr.split(","):
        part = _normalize_token(part.strip(), field)
        if not part:
            raise ConfigError(f"cron {field} 필드가 비어 있습니다.")

        step = 1
        if "/" in part:
            part, _, step_text = part.partition("/")
            if not step_text.isdigit() or int(step_text) == 0:
                raise ConfigError(f"cron {field} 필드의 간격(step) 값이 잘못되었습니다: '{step_text}'")
            step = int(step_text)
            part = part or "*"

        if part == "*":
            start, end = low, high
        elif "-" in part.lstrip("-"):
            start_text, _, end_text = part.partition("-")
            start, end = _to_int(start_text, field), _to_int(end_text, field)
        else:
            start = end = _to_int(part, field)

        if start > end:
            raise ConfigError(f"cron {field} 필드 범위가 뒤집혀 있습니다: '{part}'")
        if start < low or end > high:
            raise ConfigError(f"cron {field} 필드는 {low}~{high} 범위여야 합니다 (받은 값: '{part}').")

        values.update(range(start, end + 1, step))

    if not values:
        raise ConfigError(f"cron {field} 필드에서 유효한 값을 찾지 못했습니다: '{expr}'")
    return values


def _to_int(text: str, field: str) -> int:
    text = text.strip()
    try:
        value = int(text)
    except ValueError as exc:
        raise ConfigError(f"cron {field} 필드에 숫자가 아닌 값이 있습니다: '{text}'") from exc
    if field == "weekday" and value == 7:
        return 0
    return value


def parse_cron(expression: str) -> dict[str, set[int]]:
    """cron 문자열을 필드별 허용값 집합으로 변환."""
    if not isinstance(expression, str) or not expression.strip():
        raise ConfigError("cron: 비어 있습니다.")
    expr = _ALIASES.get(expression.strip().lower(), expression.strip())
    fields = expr.split()
    if len(fields) != 5:
        raise ConfigError(
            f"cron: 5개 필드(분 시 일 월 요일)가 필요합니다. 받은 값: '{expression}' ({len(fields)}개)"
        )
    return {name: _parse_field(value, name) for name, value in zip(_FIELD_ORDER, fields)}


def validate_cron(expression: str, *, field_name: str = "cron") -> None:
    """설정 검증용 - 잘못된 cron 이면 ConfigError."""
    try:
        parse_cron(expression)
    except ConfigError as exc:
        raise ConfigError(f"{field_name}: {exc}") from exc


def matches(parsed: dict[str, set[int]], moment: datetime) -> bool:
    """해당 분(minute)에 cron 이 발동하는지."""
    weekday = (moment.weekday() + 1) % 7  # Python: 월=0 -> cron: 일=0
    if moment.minute not in parsed["minute"] or moment.hour not in parsed["hour"]:
        return False
    if moment.month not in parsed["month"]:
        return False

    day_restricted = len(parsed["day"]) < 31
    weekday_restricted = len(parsed["weekday"]) < 7
    day_ok = moment.day in parsed["day"]
    weekday_ok = weekday in parsed["weekday"]

    # 표준 cron 규칙: 일/요일이 모두 제한되면 둘 중 하나만 맞아도 발동
    if day_restricted and weekday_restricted:
        return day_ok or weekday_ok
    return day_ok and weekday_ok


def next_cron_time(expression: str, after: datetime) -> datetime:
    """`after` 이후 가장 가까운 발동 시각 (초/마이크로초는 0)."""
    parsed = parse_cron(expression)
    candidate = (after + timedelta(minutes=1)).replace(second=0, microsecond=0)
    limit = after + timedelta(days=_MAX_LOOKAHEAD_DAYS)

    while candidate <= limit:
        if matches(parsed, candidate):
            return candidate
        # 월/일이 안 맞으면 하루 단위로 건너뛴다 (탐색 속도 개선)
        if candidate.month not in parsed["month"] or not _day_possible(parsed, candidate):
            candidate = (candidate + timedelta(days=1)).replace(hour=0, minute=0)
            continue
        candidate += timedelta(minutes=1)

    raise ConfigError(f"cron '{expression}': 앞으로 4년 안에 발동 시각이 없습니다.")


def _day_possible(parsed: dict[str, set[int]], moment: datetime) -> bool:
    weekday = (moment.weekday() + 1) % 7
    day_restricted = len(parsed["day"]) < 31
    weekday_restricted = len(parsed["weekday"]) < 7
    day_ok = moment.day in parsed["day"]
    weekday_ok = weekday in parsed["weekday"]
    if day_restricted and weekday_restricted:
        return day_ok or weekday_ok
    return day_ok and weekday_ok


def next_run(job, *, after: datetime | None = None) -> datetime | None:
    """Job 의 다음 실행 시각(타임존 인식). 더 이상 없으면 None."""
    tz = job.tzinfo
    now = after or datetime.now(tz)
    if now.tzinfo is None and tz is not None:
        now = now.replace(tzinfo=tz)

    if job.start is not None:
        start = job.start if job.start.tzinfo else job.start.replace(tzinfo=tz or now.tzinfo)
        return start if start > now else None

    if job.cron:
        naive_now = now.replace(tzinfo=None)
        naive_next = next_cron_time(job.cron, naive_now)
        return naive_next.replace(tzinfo=tz or now.tzinfo)

    return None


def upcoming(jobs: Iterable, *, after: datetime | None = None) -> list[tuple[object, datetime]]:
    """작업 목록의 다음 실행 시각을 빠른 순서대로 반환."""
    result = []
    for job in jobs:
        if not getattr(job, "enabled", True):
            continue
        when = next_run(job, after=after)
        if when is not None:
            result.append((job, when))
    return sorted(result, key=lambda pair: pair[1])
