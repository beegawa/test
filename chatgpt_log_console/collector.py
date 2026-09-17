"""수집 절차 — 웹 화면(app.py)과 스케줄러(collect.py)가 함께 쓴다.

  목록 조회(페이지네이션) → 개별 로그 JSONL 다운로드 → 정리 → DB 누적
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from compliance import ComplianceClient, ComplianceError, since_days
from records import normalize
from settings import DEFAULT_MAX_LOGS, EVENT_TYPE_CANDIDATES, PAGE_LIMIT
from store import LogStore

log = logging.getLogger(__name__)

EVENT_TYPE_META = "event_types"
EVENT_TYPE_CHECKED_META = "event_types_checked_at"
_BATCH = 200


@dataclass
class CollectResult:
    """수집 한 번의 결과."""

    event_types: list[str] = field(default_factory=list)
    listed: int = 0        # 목록에서 확인한 로그 id 수
    fetched: int = 0       # 실제로 내려받은 로그 파일 수
    records: int = 0       # 파싱된 레코드 수
    saved: int = 0         # DB 에 새로 들어간 수(중복 제외)
    truncated: bool = False
    errors: list[str] = field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""

    def to_dict(self) -> dict:
        return {
            "event_types": self.event_types,
            "listed": self.listed,
            "fetched": self.fetched,
            "records": self.records,
            "saved": self.saved,
            "duplicates": max(self.records - self.saved, 0),
            "truncated": self.truncated,
            "errors": self.errors,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


def resolve_event_types(
    client: ComplianceClient, store: LogStore, *, force: bool = False
) -> list[str]:
    """쓸 수 있는 event_type 을 정한다.

    한 번 확인하면 DB(meta)에 기억해 두고 다시 찔러보지 않는다.
    후보가 전부 실패하면 빈 목록을 돌려주고, 호출한 쪽은 필터 없이(전체 이벤트) 수집한다.
    """
    if not force:
        cached = store.get_meta(EVENT_TYPE_META)
        if isinstance(cached, list) and cached:
            return cached
    usable = client.detect_event_types(EVENT_TYPE_CANDIDATES)
    store.set_meta(EVENT_TYPE_META, usable)
    store.set_meta(EVENT_TYPE_CHECKED_META, _now())
    return usable


def collect(
    client: ComplianceClient,
    store: LogStore,
    *,
    days: int | None = None,
    after: str | None = None,
    event_types: list[str] | None = None,
    incremental: bool = False,
    max_logs: int = DEFAULT_MAX_LOGS,
    page_limit: int = PAGE_LIMIT,
    progress: Callable[[dict], None] | None = None,
    cancel: "threading.Event | None" = None,
) -> CollectResult:
    """로그를 받아 DB 에 누적한다.

    days       : 최근 N 일치를 받는다 (after 가 없을 때)
    after      : ISO 시각. 이 시각 이후만 받는다 (days 보다 우선)
    incremental: True 면 마지막으로 저장한 시각부터 이어 받는다 (스케줄러용)
    """
    result = CollectResult(started_at=_now())
    types = event_types if event_types is not None else resolve_event_types(client, store)
    result.event_types = list(types)
    targets: list[str | None] = list(types) if types else [None]
    if not types:
        log.warning("쓸 수 있는 event_type 을 찾지 못해 필터 없이 전체 이벤트를 수집합니다.")

    remaining = max_logs
    buffer: list[dict] = []

    def flush() -> None:
        if buffer:
            result.saved += store.add_many(buffer)
            buffer.clear()

    def report() -> None:
        if progress:
            progress(result.to_dict())

    for event_type in targets:
        if cancel is not None and cancel.is_set():
            break
        start_from = _start_point(store, event_type, days=days, after=after, incremental=incremental)
        log.info("수집 시작: event_type=%s after=%s", event_type or "(전체)", start_from or "(처음부터)")
        newest_cursor = None
        try:
            for log_id, page_cursor in client.iter_log_ids(
                event_type=event_type,
                after=start_from,
                limit=page_limit,
                max_items=remaining,
            ):
                if cancel is not None and cancel.is_set():
                    break
                result.listed += 1
                try:
                    raw_records = client.fetch_log(log_id)
                except ComplianceError as exc:
                    result.errors.append(f"{log_id}: {exc}")
                    log.warning("로그 %s 다운로드 실패: %s", log_id, exc)
                    continue
                result.fetched += 1
                if result.fetched % 10 == 0:
                    report()          # 목록만 길게 도는 구간에서도 살아 있음을 알린다
                for index, raw in enumerate(raw_records):
                    buffer.append(normalize(raw, log_id=log_id, index=index, event_type_hint=event_type))
                    result.records += 1
                if page_cursor:
                    newest_cursor = page_cursor
                if len(buffer) >= _BATCH:
                    flush()
                    report()
                remaining -= 1
                if remaining <= 0:
                    result.truncated = True
                    break
        except ComplianceError as exc:
            result.errors.append(f"{event_type or '(전체)'}: {exc}")
            log.error("수집 중 오류: %s", exc)
        finally:
            flush()

        if newest_cursor:
            store.set_cursor(event_type, newest_cursor)
        report()
        if remaining <= 0:
            break

    flush()
    result.finished_at = _now()
    report()
    log.info(
        "수집 완료: 목록 %d건 / 다운로드 %d건 / 레코드 %d건 / 신규 저장 %d건",
        result.listed, result.fetched, result.records, result.saved,
    )
    return result


def _start_point(
    store: LogStore, event_type: str | None, *, days: int | None, after: str | None, incremental: bool
) -> str | None:
    if after:
        return after
    if incremental:
        # 마지막 페이지 커서가 가장 정확하고, 없으면 마지막으로 저장한 이벤트 시각을 쓴다.
        return store.get_cursor(event_type) or store.latest_ts(event_type)
    if days:
        return since_days(days)
    return None


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
