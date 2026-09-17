"""SQLite 누적 저장소.

API 의 로그 보관 기간은 30일이라, 그보다 오래된 데이터는 다시 받을 수 없다.
그래서 받은 건 전부 여기에 쌓아 두고(중복은 INSERT OR IGNORE 로 무시) 이후
조회·검색은 API 가 아니라 이 DB 를 본다.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

log = logging.getLogger(__name__)

TABLES = """
CREATE TABLE IF NOT EXISTS logs(
    id            TEXT PRIMARY KEY,   -- 로그 고유 id (중복 방지)
    event_type    TEXT,
    ts            TEXT,               -- 이벤트 시각 (ISO 8601, UTC)
    user          TEXT,               -- 사용자 식별자
    action        TEXT,               -- 무슨 일이 있었는지 (CONVERSATION_DELETE 등)
    conversation_id TEXT,             -- 관련 대화 id (있는 로그만)
    content       TEXT,               -- 검색용 평문 (원본에서 뽑아낸 내용)
    summary       TEXT,               -- 표에 보여줄 한 줄 요약
    source_log_id TEXT,               -- 내려받은 로그 파일 id
    raw           TEXT,               -- 원본 JSON 전체
    fetched_at    TEXT                -- 우리가 받은 시각
);

CREATE TABLE IF NOT EXISTS meta(
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

# 인덱스는 열이 모두 갖춰진 뒤에 만든다.
INDEXES = """
CREATE INDEX IF NOT EXISTS idx_ts    ON logs(ts);
CREATE INDEX IF NOT EXISTS idx_user  ON logs(user);
CREATE INDEX IF NOT EXISTS idx_event ON logs(event_type);
CREATE INDEX IF NOT EXISTS idx_conv  ON logs(conversation_id);
"""

COLUMNS = ("id", "event_type", "ts", "user", "action", "conversation_id",
           "content", "summary", "source_log_id", "raw", "fetched_at")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class LogStore:
    """스레드 하나가 수집하고 다른 스레드가 조회하므로 연결 하나 + 락으로 보호한다."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(TABLES)
            self._migrate()                     # 예전 DB 에 빠진 열을 먼저 채우고
            self._conn.executescript(INDEXES)   # 그다음에 인덱스를 만든다
            self._conn.commit()
        self._restrict_permissions()

    def _migrate(self) -> None:
        """예전 버전으로 만든 DB 에 새 열을 채워 넣는다. 기존 데이터는 그대로 둔다."""
        있는열 = {행[1] for 행 in self._conn.execute("PRAGMA table_info(logs)")}
        for 열, 정의 in (("action", "TEXT"), ("conversation_id", "TEXT")):
            if 열 not in 있는열:
                self._conn.execute(f"ALTER TABLE logs ADD COLUMN {열} {정의}")
                log.info("DB 에 %s 열을 추가했습니다.", 열)

    def _restrict_permissions(self) -> None:
        """DB 파일에는 대화 내용이 담긴다. 소유자만 읽도록 둔다."""
        if str(self.path) == ":memory:":
            return
        try:
            self.path.chmod(0o600)
        except OSError:  # pragma: no cover - 윈도우 등
            pass

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> "LogStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------ 저장
    def add_many(self, records: Iterable[dict]) -> int:
        """정리된 레코드를 누적 저장하고 '새로 들어간 건수' 를 돌려준다."""
        rows = []
        fetched = _now()
        for record in records:
            if not record or not record.get("id"):
                continue
            raw = record.get("raw")
            rows.append(
                (
                    str(record["id"]),
                    record.get("event_type") or "",
                    record.get("ts") or "",
                    record.get("user") or "",
                    record.get("action") or "",
                    record.get("conversation_id") or "",
                    record.get("content") or "",
                    record.get("summary") or "",
                    record.get("source_log_id") or "",
                    raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False),
                    fetched,
                )
            )
        if not rows:
            return 0
        placeholders = ", ".join("?" * len(COLUMNS))
        with self._lock:
            before = self._conn.total_changes
            self._conn.executemany(
                f"INSERT OR IGNORE INTO logs({', '.join(COLUMNS)}) VALUES({placeholders})", rows
            )
            self._conn.commit()
            return self._conn.total_changes - before

    # ------------------------------------------------------------ 조회
    def search(
        self,
        *,
        start: str | None = None,
        end: str | None = None,
        user: str | None = None,
        keyword: str | None = None,
        event_type: str | None = None,
        conversation_id: str | None = None,
        fetched_since: str | None = None,
        limit: int = 500,
        offset: int = 0,
    ) -> list[dict]:
        where, params = self._where(start, end, user, keyword, event_type, fetched_since,
                                    conversation_id)
        sql = (
            f"SELECT {', '.join(COLUMNS)} FROM logs {where} "
            "ORDER BY ts DESC, id DESC LIMIT ? OFFSET ?"
        )
        with self._lock:
            cursor = self._conn.execute(sql, [*params, int(limit), int(offset)])
            return [dict(row) for row in cursor.fetchall()]

    def get(self, record_id: str) -> dict | None:
        """id 로 한 건을 꺼낸다(자세히 보기용, raw 포함)."""
        with self._lock:
            row = self._conn.execute(
                f"SELECT {', '.join(COLUMNS)} FROM logs WHERE id = ?", (record_id,)
            ).fetchone()
        return dict(row) if row else None

    def count(
        self,
        *,
        start: str | None = None,
        end: str | None = None,
        user: str | None = None,
        keyword: str | None = None,
        event_type: str | None = None,
        conversation_id: str | None = None,
        fetched_since: str | None = None,
    ) -> int:
        where, params = self._where(start, end, user, keyword, event_type, fetched_since,
                                    conversation_id)
        with self._lock:
            return int(self._conn.execute(f"SELECT COUNT(*) FROM logs {where}", params).fetchone()[0])

    @staticmethod
    def _where(start, end, user, keyword, event_type, fetched_since=None,
               conversation_id=None) -> tuple[str, list]:
        clauses: list[str] = []
        params: list = []
        if start:
            clauses.append("ts >= ?")
            params.append(start)
        if end:
            clauses.append("ts <= ?")
            params.append(end)
        if user:
            clauses.append("user LIKE ?")
            params.append(f"%{user}%")
        if event_type:
            clauses.append("event_type = ?")
            params.append(event_type)
        if conversation_id:
            clauses.append("conversation_id = ?")
            params.append(conversation_id)
        if fetched_since:
            # 이번 수집에서 새로 들어온 것만 보고 싶을 때
            clauses.append("fetched_at >= ?")
            params.append(fetched_since)
        if keyword:
            clauses.append("(content LIKE ? OR summary LIKE ? OR action LIKE ? OR raw LIKE ?)")
            params += [f"%{keyword}%"] * 4
        return ("WHERE " + " AND ".join(clauses)) if clauses else "", params

    def stats(self) -> dict:
        """전체 건수·기간·이벤트별 건수·사용자 수."""
        with self._lock:
            total, oldest, newest = self._conn.execute(
                "SELECT COUNT(*), MIN(NULLIF(ts,'')), MAX(NULLIF(ts,'')) FROM logs"
            ).fetchone()
            by_event = {
                row[0] or "(없음)": row[1]
                for row in self._conn.execute(
                    "SELECT event_type, COUNT(*) FROM logs GROUP BY event_type ORDER BY 2 DESC"
                )
            }
            users = int(
                self._conn.execute("SELECT COUNT(DISTINCT user) FROM logs WHERE user <> ''").fetchone()[0]
            )
        return {
            "total": int(total or 0),
            "oldest": oldest or "",
            "newest": newest or "",
            "by_event": by_event,
            "users": users,
        }

    def users(self, limit: int = 500) -> list[str]:
        with self._lock:
            return [
                row[0]
                for row in self._conn.execute(
                    "SELECT user FROM logs WHERE user <> '' GROUP BY user ORDER BY COUNT(*) DESC LIMIT ?",
                    (limit,),
                )
            ]

    def latest_ts(self, event_type: str | None = None) -> str | None:
        """마지막으로 저장한 이벤트 시각. 증분 수집의 시작점."""
        sql = "SELECT MAX(ts) FROM logs WHERE ts <> ''"
        params: list = []
        if event_type:
            sql += " AND event_type = ?"
            params.append(event_type)
        with self._lock:
            return self._conn.execute(sql, params).fetchone()[0] or None

    # ------------------------------------------------------------ meta
    def get_meta(self, key: str, default=None):
        with self._lock:
            row = self._conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row[0])
        except (TypeError, json.JSONDecodeError):
            return row[0]

    def set_meta(self, key: str, value) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO meta(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, json.dumps(value, ensure_ascii=False)),
            )
            self._conn.commit()

    # 증분 수집 커서 (event_type 별로 따로 기억한다)
    def get_cursor(self, event_type: str | None) -> str | None:
        return self.get_meta(f"cursor::{event_type or '_all'}")

    def set_cursor(self, event_type: str | None, value: str | None) -> None:
        if value:
            self.set_meta(f"cursor::{event_type or '_all'}", value)
