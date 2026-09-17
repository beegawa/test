"""내려받은 로그 JSON 한 건을 표/DB 에 넣을 모양으로 정리한다.

대화 로그의 정확한 필드 이름은 워크스페이스마다·이벤트 종류마다 다를 수 있어서
'이 키일 것이다' 라고 단정하지 않는다. 후보 키를 얕은 곳부터 훑어 찾고,
못 찾으면 비워 둔 채 원본(raw)은 그대로 보관한다. 나중에 실제 응답을 보고
후보 목록만 늘리면 된다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# 파서를 고칠 때마다 올린다. 저장된 DB 의 값이 이 버전보다 낮으면
# 원본(raw)을 다시 해석해 채운다. 다시 내려받을 필요가 없다.
PARSER_VERSION = 2

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
    "prompt_text", "prompt", "completion", "output", "title",
)
# 실제 로그에서 '무슨 일이 있었는지' 를 나타내는 자리들
ACTION_KEYS = ("action", "detail_type", "log_type", "event_type")
# 이 값들은 내용이 아니라 요청 파라미터라서 요약에 넣으면 방해가 된다
NOISE_KEYS = ("_meta", "top", "order_by", "limit", "offset", "cursor")
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


def extract_action(raw: dict) -> str:
    """무슨 일이 있었는지. 예: CONVERSATION_DELETE, logout_success, request"""
    for 자리 in (raw, raw.get("action_data"), raw.get("event_details")):
        if not isinstance(자리, dict):
            continue
        for key in ACTION_KEYS:
            값 = 자리.get(key)
            if isinstance(값, str) and 값:
                return 값
    return ""


def extract_conversation_id(raw: dict) -> str:
    값 = _walk(raw, ("conversation_id", "conversationId"))
    return str(값) if 값 else ""


def _고유이름(raw: dict) -> str:
    """앱 이름·모델처럼 요약에 보탬이 되는 한 조각."""
    for key in ("app_name", "model", "client_id", "role"):
        값 = _walk(raw, (key,))
        if isinstance(값, str) and 값:
            return 값
    return ""


def describe(raw: dict, content: str) -> str:
    """표에 한 줄로 보여줄 설명.

    대화 내용이 있으면 그것을, 없으면 '무엇을 했는지'를 보여준다.
    감사·인증 로그는 내용이 없는 게 정상이라 빈칸으로 두면 안 된다.
    """
    조각 = [값 for 값 in (extract_action(raw), _고유이름(raw)) if 값]
    머리 = " · ".join(dict.fromkeys(조각))
    본문 = summarize(content, limit=120) if content else ""
    if 머리 and 본문:
        return f"{머리} — {본문}"
    return 머리 or 본문


def _내용찾기(raw: dict):
    """요청 파라미터 같은 잡음은 빼고 실제 내용만 고른다."""
    값 = _walk(raw, CONTENT_KEYS)
    if isinstance(값, dict):
        값 = {키: 하위 for 키, 하위 in 값.items() if 키 not in NOISE_KEYS}
        if not 값:
            return None
    return 값


def normalize(raw: dict, *, log_id: str, index: int = 0, event_type_hint: str | None = None) -> dict:
    """원본 한 건 → DB 한 행.

    id 는 중복 저장을 막는 기준이다. 원본에 고유 id 가 있으면 그것을 쓰고,
    없으면 '내려받은 로그 id + 줄 번호' 로 만든다.

    로그 종류(event_type)는 **우리가 요청한 값**을 우선한다. 레코드 안의
    event_type 은 세부 동작(PROMPT_SENT 등)을 담고 있어 종류와 다르기 때문이다.
    """
    own_id = _walk(raw, ID_KEYS)
    record_id = str(own_id) if own_id else f"{log_id}#{index}"
    event_type = event_type_hint or raw.get("type") or _walk(raw, TYPE_KEYS) or ""
    content = flatten_content(_내용찾기(raw))
    return {
        "id": record_id,
        "event_type": str(event_type),
        "ts": normalize_ts(_walk(raw, TS_KEYS)),
        "user": normalize_user(_walk(raw, USER_KEYS)),
        "action": extract_action(raw),
        "conversation_id": extract_conversation_id(raw),
        "content": content,
        "summary": describe(raw, content),
        "source_log_id": log_id,
        "raw": raw,
    }
