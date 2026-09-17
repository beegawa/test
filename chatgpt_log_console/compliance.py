"""OpenAI Compliance Logs Platform API 클라이언트.

  GET {base}/workspaces/{id}/logs           목록(페이지네이션)
  GET {base}/workspaces/{id}/logs/{log_id}  개별 로그(JSONL, 리다이렉트 따라감)

목록 응답: {"data":[{"id":"log_..."}], "has_more": true, "last_end_time": "..."}
has_more 가 true 면 last_end_time 을 다음 요청의 after 로 넣어 반복한다.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterator

import requests

from settings import (
    BASE_URL,
    EVENT_TYPE_CANDIDATES,
    HTTP_TIMEOUT,
    MAX_RETRIES,
    ORG_ID,
    PAGE_LIMIT,
    RETENTION_DAYS,
    WORKSPACE_ID,
)

log = logging.getLogger(__name__)


# ------------------------------------------------------------------ 오류
class ComplianceError(Exception):
    """Compliance API 호출 실패."""


class AuthError(ComplianceError):
    """401 - 키가 무효하거나 만료되었다."""


class ForbiddenError(ComplianceError):
    """403 - 키에 '규정 준수 로깅 플랫폼' 읽기 권한이 없다."""


class BadRequestError(ComplianceError):
    """400 - 값이 이 워크스페이스에서 통하지 않는다(대개 event_type)."""


class ParameterError(ComplianceError):
    """422 - 필수 쿼리 파라미터가 빠졌거나 값이 잘못되었다."""


class RateLimitError(ComplianceError):
    """429 - 재시도를 다 쓰고도 레이트리밋이 풀리지 않았다."""


# ------------------------------------------------------------------ 시간 유틸
def to_iso(moment: datetime) -> str:
    """API 가 받는 ISO 8601(UTC, 초 단위) 문자열로 만든다."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def since_days(days: int) -> str:
    """지금부터 days 일 전 시각(ISO)."""
    return to_iso(datetime.now(timezone.utc) - timedelta(days=days))


def _default_after() -> str:
    """after 가 지정되지 않았을 때 쓰는 기본값 - 보관 기간 전체(30일)."""
    return since_days(RETENTION_DAYS)


@dataclass
class Page:
    """목록 한 페이지."""

    ids: list[str] = field(default_factory=list)
    has_more: bool = False
    last_end_time: str | None = None


class ComplianceClient:
    """관리자 키 하나로 목록 조회와 개별 로그 다운로드를 수행한다."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = BASE_URL,
        workspace_id: str | None = None,
        org_id: str | None = None,
        timeout: int = HTTP_TIMEOUT,
        max_retries: int = MAX_RETRIES,
        session=None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if not (api_key or "").strip():
            raise AuthError("관리자 키가 비어 있습니다.")
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.org_id = org_id if org_id is not None else ORG_ID
        self.workspace_id = workspace_id if workspace_id is not None else WORKSPACE_ID
        if not self.org_id and not self.workspace_id:
            raise ComplianceError("workspace_id 또는 org_id 중 하나는 있어야 합니다.")
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = session or requests.Session()
        self._sleep = sleep

    # -------------------------------------------------------------- 내부
    @property
    def scope_path(self) -> str:
        """조직 ID 가 지정돼 있으면 조직 스코프, 아니면 워크스페이스 스코프."""
        if self.org_id:
            return f"/organizations/{self.org_id}"
        return f"/workspaces/{self.workspace_id}"

    @property
    def scope_label(self) -> str:
        return f"organization:{self.org_id}" if self.org_id else f"workspace:{self.workspace_id}"

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }

    def _request(self, path: str, *, params: dict | None = None, stream: bool = False):
        """GET 요청. 429/5xx 는 지수 백오프로 재시도한다."""
        url = f"{self.base_url}{path}"
        delay = 1.0
        last_error = ""

        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.session.get(
                    url,
                    headers=self._headers(),
                    params=params,
                    timeout=self.timeout,
                    allow_redirects=True,
                    stream=stream,
                )
            except requests.RequestException as exc:
                last_error = f"연결 실패: {exc}"
                if attempt == self.max_retries:
                    raise ComplianceError(f"{url} 요청에 실패했습니다. {last_error}") from exc
                self._sleep(delay)
                delay = min(delay * 2, 30)
                continue

            status = response.status_code
            if status == 200:
                return response
            if status == 401:
                raise AuthError(
                    "관리자 키가 무효하거나 만료되었습니다. (401)"
                    " - 일반 API 키(sk-proj-...)가 아니라 관리자 콘솔 > 인증 정보 >"
                    " 관리자 키에서 발급한 키여야 합니다."
                    + _server_says(response)
                )
            if status == 403:
                raise ForbiddenError(
                    "이 키에는 '규정 준수 로깅 플랫폼(Compliance Logs Platform)' 읽기 권한이"
                    " 없습니다. (403) - 관리자 콘솔에서 키의 권한을 확인하세요."
                    + _server_says(response)
                )
            if status == 400:
                raise BadRequestError(
                    "요청이 거절되었습니다. (400)" + _server_says(response)
                )
            if status == 422:
                raise ParameterError(
                    "요청 파라미터가 잘못되었습니다. (422)" + _server_says(response)
                )
            if status == 404:
                raise ComplianceError(
                    f"주소를 찾지 못했습니다. (404) 워크스페이스/조직 ID 가 맞는지 확인하세요."
                    f" 요청한 곳: {url}" + _server_says(response)
                )
            if status == 429 or status >= 500:
                wait = _retry_after(response) or delay
                last_error = f"HTTP {status}"
                if attempt == self.max_retries:
                    if status == 429:
                        raise RateLimitError(
                            f"레이트리밋(429)이 {self.max_retries}회 재시도 후에도 풀리지 않았습니다."
                        )
                    raise ComplianceError(f"서버 오류가 계속됩니다. ({status})")
                log.warning("%s - %.0f초 후 재시도 (%d/%d)", last_error, wait, attempt, self.max_retries)
                self._sleep(wait)
                delay = min(delay * 2, 30)
                continue

            raise ComplianceError(
                f"요청이 거절되었습니다. (HTTP {status}){_server_says(response)}"
            )

        raise ComplianceError(f"{url} 요청에 실패했습니다. {last_error}")  # pragma: no cover

    # -------------------------------------------------------------- 공개 API
    def validate(self, candidates: list[str] | None = None) -> dict:
        """키가 실제로 쓸 수 있는지 확인한다.

        이 API 는 event_type 과 after 를 필수로 요구하므로(빠지면 422), 후보
        event_type 을 하나씩 넣어 보고 **하나라도 200 이면 통과**로 본다.
        키 자체가 문제인 401/403 은 바로 올려 보낸다.
        """
        after = _default_after()
        last_error: ComplianceError | None = None
        for event_type in (candidates or EVENT_TYPE_CANDIDATES):
            try:
                body = _json(self._request(
                    f"{self.scope_path}/logs",
                    params={"limit": 1, "event_type": event_type, "after": after},
                ))
            except (BadRequestError, ParameterError) as exc:
                last_error = exc
                log.info("event_type %s 로는 확인되지 않음: %s", event_type, exc)
                continue
            return {
                "ok": True,
                "scope": self.scope_label,
                "event_type": event_type,
                "sample_count": len(body.get("data") or []),
            }
        raise last_error or ComplianceError("어떤 event_type 으로도 응답을 받지 못했습니다.")

    def probe_event_type(self, event_type: str, *, after: str | None = None) -> bool:
        """해당 event_type 이 이 워크스페이스에서 통하는지 시험한다."""
        try:
            self._request(
                f"{self.scope_path}/logs",
                params={"limit": 1, "event_type": event_type, "after": after or _default_after()},
            )
            return True
        except (BadRequestError, ParameterError) as exc:
            log.info("event_type %s 사용 불가: %s", event_type, exc)
            return False

    def detect_event_types(self, candidates: list[str]) -> list[str]:
        """후보를 순서대로 시험해 정상 응답하는 것만 골라낸다."""
        usable = [name for name in candidates if self.probe_event_type(name)]
        log.info("사용 가능한 event_type: %s", ", ".join(usable) or "(없음)")
        return usable

    def list_page(
        self, *, event_type: str | None = None, after: str | None = None, limit: int = PAGE_LIMIT
    ) -> Page:
        # event_type 과 after 는 이 API 의 필수 파라미터다. 빠지면 422 가 난다.
        params: dict = {"limit": limit, "after": after or _default_after()}
        if event_type:
            params["event_type"] = event_type
        body = _json(self._request(f"{self.scope_path}/logs", params=params))
        ids = [item.get("id") for item in (body.get("data") or []) if isinstance(item, dict) and item.get("id")]
        return Page(
            ids=ids,
            has_more=bool(body.get("has_more")),
            last_end_time=body.get("last_end_time"),
        )

    def iter_log_ids(
        self,
        *,
        event_type: str | None = None,
        after: str | None = None,
        limit: int = PAGE_LIMIT,
        max_items: int | None = None,
        on_page: Callable[[Page], None] | None = None,
    ) -> Iterator[tuple[str, str | None]]:
        """has_more 가 끝날 때까지 로그 id 를 (id, 그 페이지의 last_end_time) 로 흘려보낸다."""
        cursor = after
        seen = 0
        guard = None

        while True:
            page = self.list_page(event_type=event_type, after=cursor, limit=limit)
            if on_page:
                on_page(page)
            for log_id in page.ids:
                yield log_id, page.last_end_time
                seen += 1
                if max_items is not None and seen >= max_items:
                    return
            if not page.has_more or not page.last_end_time:
                return
            if page.last_end_time == guard:
                # 커서가 제자리면 무한 루프가 된다. 서버가 같은 값을 계속 주면 멈춘다.
                log.warning("페이지 커서가 더 나아가지 않아 수집을 멈춥니다: %s", guard)
                return
            guard = cursor = page.last_end_time

    def fetch_log(self, log_id: str) -> list[dict]:
        """개별 로그를 내려받아 JSONL 을 파싱한다. 한 줄에 JSON 하나."""
        response = self._request(f"{self.scope_path}/logs/{log_id}")
        records: list[dict] = []
        for line in response.text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                log.warning("로그 %s 의 한 줄을 해석하지 못했습니다.", log_id)
                continue
            if isinstance(parsed, list):
                records.extend(item for item in parsed if isinstance(item, dict))
            elif isinstance(parsed, dict):
                records.append(parsed)
        return records


def _retry_after(response) -> float | None:
    value = (getattr(response, "headers", None) or {}).get("Retry-After")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _json(response) -> dict:
    try:
        body = response.json()
    except ValueError as exc:
        raise ComplianceError("응답이 JSON 이 아닙니다.") from exc
    if not isinstance(body, dict):
        raise ComplianceError("응답 형식이 예상과 다릅니다.")
    return body


def _server_says(response) -> str:
    """서버가 보낸 설명을 그대로 덧붙인다. 원인 파악에 이게 제일 중요하다."""
    message = ""
    try:
        body = response.json()
        if isinstance(body, dict):
            error = body.get("error")
            message = (error.get("message") if isinstance(error, dict) else error) or body.get("message") or ""
            detail = body.get("detail")
            if not message and detail:
                # 예: [{"loc":["query","event_type"],"msg":"Field required"}, ...]
                if isinstance(detail, list):
                    message = "; ".join(
                        f"{'.'.join(str(x) for x in (item.get('loc') or []))}: {item.get('msg')}"
                        if isinstance(item, dict) else str(item)
                        for item in detail
                    )
                else:
                    message = str(detail)
    except Exception:
        message = ""
    if not message:
        message = (getattr(response, "text", "") or "").strip().replace("\n", " ")
    message = str(message)[:300]
    return f"\n서버 응답: {message}" if message else ""
