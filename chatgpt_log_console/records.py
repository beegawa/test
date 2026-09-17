"""내려받은 로그 JSON 한 건을 표/DB 에 넣을 모양으로 정리한다.

대화 로그의 정확한 필드 이름은 워크스페이스마다·이벤트 종류마다 다를 수 있어서
'이 키일 것이다' 라고 단정하지 않는다. 후보 키를 얕은 곳부터 훑어 찾고,
못 찾으면 비워 둔 채 원본(raw)은 그대로 보관한다. 나중에 실제 응답을 보고
후보 목록만 늘리면 된다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

ID_KEYS = ("id", "log_id", "event_id", "message_id", "uuid")
TYPE_KEYS = ("event_type", "type", "event", "event_name")
TS_KEYS = (
    "timestamp", "event_time", "created_at", "created", "time", "ts",
    "occurred_at", "start_time", "date",
)
USER_KEYS = (
    "user_email", "email", "user_name", "actor_email", "actor", "user",
    "user_id", "account", "member",
)
CONTENT_KEYS = (
    "messages", "conversation", "content", "text", "message", "body",
    "prompt", "completion", "input", "output", "title",
)
_MAX_DEPTH = 4


def _walk(value: Any, keys: tuple[str, ...], depth: int = 0):
    """후보 키를 너비 우선으로 찾는다. 얕은 곳에 있는 값을 우선한다."""
    if depth > _MAX_DEPTH or not isinstance(value, dict):
        return None
    for key in keys:
        if key in value and value[key] not in (None, "", [], {}):
            return value[key]
    for nested in value.values():
        if isinstance(nested, dict):
            found = _walk(nested, keys, depth + 1)
            if found is not None:
                return found
        elif isinstance(nested, list):
            for item in nested:
                if isinstance(item, dict):
                    found = _walk(item, keys, depth + 1)
                    if found is not None:
                        return found
    return None


def normalize_ts(value: Any) -> str:
    """시각을 ISO 8601(UTC) 문자열로 통일한다. 못 읽으면 빈 문자열."""
    if value in (None, ""):
        return ""
    if isinstance(value, (int, float)):
        seconds = float(value)
        if seconds > 1e11:       # 밀리초로 들어온 경우
            seconds /= 1000.0
        try:
            return datetime.fromtimestamp(seconds, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except (OverflowError, OSError, ValueError):
            return ""
    text = str(value).strip()
    if not text:
        return ""
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        if text.isdigit():
            return normalize_ts(int(text))
        return text  # 해석 못 해도 원문을 남긴다(정렬은 문자열 기준)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_user(value: Any) -> str:
    """사용자 식별자를 문자열로 만든다. dict 면 이메일 > 이름 > id 순."""
    if value in (None, ""):
        return ""
    if isinstance(value, dict):
        for key in ("email", "user_email", "name", "user_name", "id", "user_id"):
            if value.get(key):
                return str(value[key])
        return ""
    return str(value)


def flatten_content(value: Any, *, limit: int = 20000) -> str:
    """대화 내용을 검색·표시가 가능한 평문으로 편다."""
    parts: list[str] = []

    def walk(node: Any, depth: int = 0) -> None:
        if depth > 6 or len("".join(parts)) > limit:
            return
        if isinstance(node, str):
            text = node.strip()
            if text:
                parts.append(text)
        elif isinstance(node, (int, float, bool)):
            parts.append(str(node))
        elif isinstance(node, list):
            for item in node:
                walk(item, depth + 1)
        elif isinstance(node, dict):
            role = node.get("role") or node.get("author") or node.get("speaker")
            body = None
            for key in ("content", "text", "message", "parts", "value", "body"):
                if key in node:
                    body = node[key]
                    break
            if body is None:
                for item in node.values():
                    walk(item, depth + 1)
                return
            before = len(parts)
            walk(body, depth + 1)
            if role and len(parts) > before:
                parts[before] = f"{_role_name(role)}: {parts[before]}"

    walk(value)
    joined = "\n".join(parts).strip()
    return joined[:limit]


def _role_name(role: Any) -> str:
    text = normalize_user(role) if isinstance(role, dict) else str(role)
    return {"user": "사용자", "assistant": "ChatGPT", "system": "시스템"}.get(text, text)


def summarize(text: str, *, limit: int = 160) -> str:
    """표에 한 줄로 보여줄 요약."""
    one_line = " ".join((text or "").split())
    return one_line if len(one_line) <= limit else one_line[: limit - 1] + "…"


def normalize(raw: dict, *, log_id: str, index: int = 0, event_type_hint: str | None = None) -> dict:
    """원본 한 건 → DB 한 행.

    id 는 중복 저장을 막는 기준이다. 원본에 고유 id 가 있으면 그것을 쓰고,
    없으면 '내려받은 로그 id + 줄 번호' 로 만든다.
    """
    own_id = _walk(raw, ID_KEYS)
    record_id = str(own_id) if own_id else f"{log_id}#{index}"
    event_type = _walk(raw, TYPE_KEYS) or event_type_hint or ""
    content = flatten_content(_walk(raw, CONTENT_KEYS))
    return {
        "id": record_id,
        "event_type": str(event_type),
        "ts": normalize_ts(_walk(raw, TS_KEYS)),
        "user": normalize_user(_walk(raw, USER_KEYS)),
        "content": content,
        "summary": summarize(content),
        "source_log_id": log_id,
        "raw": raw,
    }
