"""대화 로그 엔드포인트 정밀 탐색.

explore_api.py 가 결정적인 단서를 찾았다.

  /conversations       → 410 "Compliance Logs Platform conversation logs 로 옮기라"
  /conversations/logs  → 405 Method Not Allowed  ← 경로는 있는데 GET 이 아니다
  /users               → 400 Invalid 'after' value ← 있는데 after 형식이 다르다

그래서 이 도구는 (1) 405 응답의 Allow 헤더로 허용 메서드를 읽고, (2) GET 말고
POST/OPTIONS 도 시도하며, (3) after 값의 형식을 여러 가지로 바꿔 본다.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import requests  # noqa: E402

import keystore  # noqa: E402
from settings import BASE_URL, ORG_ID, RETENTION_DAYS, WORKSPACE_ID  # noqa: E402

기준 = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)

AFTER_형식 = [
    ("ISO(초)", 기준.strftime("%Y-%m-%dT%H:%M:%SZ")),
    ("ISO(마이크로초)", 기준.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"),
    ("ISO(오프셋)", 기준.strftime("%Y-%m-%dT%H:%M:%S+00:00")),
    ("날짜만", 기준.strftime("%Y-%m-%d")),
    ("유닉스(초)", str(int(기준.timestamp()))),
    ("유닉스(밀리초)", str(int(기준.timestamp() * 1000))),
]

대상_경로 = [
    "/conversations/logs",
    "/conversations",
    "/logs/conversations",
    "/conversation_logs",
    "/users",
]


def 요청(session, method, url, key, *, params=None, body=None, timeout=30):
    try:
        response = session.request(
            method, url,
            headers={"Authorization": f"Bearer {key}", "Accept": "application/json",
                     "Content-Type": "application/json"},
            params=params or {},
            data=json.dumps(body) if body is not None else None,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        return None, f"연결 실패: {type(exc).__name__}", {}
    본문 = (response.text or "").strip().replace("\n", " ")
    return response.status_code, 본문[:400], dict(response.headers)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="대화 로그 엔드포인트 정밀 탐색")
    parser.add_argument("--key")
    parser.add_argument("--workspace", default=WORKSPACE_ID)
    parser.add_argument("--org", default=ORG_ID)
    parser.add_argument("--base", default=BASE_URL)
    args = parser.parse_args(argv)

    key = args.key or keystore.load_key()
    if not key:
        print("저장된 키가 없습니다.")
        return 2

    base = args.base.rstrip("/")
    스코프 = f"/organizations/{args.org}" if args.org else f"/workspaces/{args.workspace}"
    session = requests.Session()
    기본after = AFTER_형식[0][1]

    print()
    print("=" * 74)
    print("  대화 로그 엔드포인트 정밀 탐색")
    print("=" * 74)
    print(f"  키   : {keystore.mask(key)}")
    print()

    # ── 1. 허용되는 HTTP 메서드 ─────────────────────────────────────
    print("── 1. 어떤 HTTP 메서드가 허용되는가 " + "─" * 36)
    for 뒤 in 대상_경로:
        url = f"{base}{스코프}{뒤}"
        print(f"\n  ● {뒤}")
        for method in ("OPTIONS", "GET", "POST"):
            상태, 본문, 헤더 = 요청(
                session, method, url, key,
                params={"limit": 1, "after": 기본after} if method == "GET" else None,
                body={"limit": 1, "after": 기본after} if method == "POST" else None,
            )
            allow = 헤더.get("Allow") or 헤더.get("allow") or ""
            표시 = "★" if 상태 == 200 else " "
            print(f"    {표시}[{상태}] {method:<8} {('Allow: ' + allow) if allow else ''}")
            if 상태 not in (404, 405) or allow:
                print(f"           {본문[:300]}")
            time.sleep(0.1)
    print()

    # ── 2. after 형식 ───────────────────────────────────────────────
    print("── 2. after 는 어떤 형식을 받는가 (/users 로 확인) " + "─" * 21)
    for 이름, 값 in AFTER_형식:
        상태, 본문, _ = 요청(session, "GET", f"{base}{스코프}/users", key,
                           params={"limit": 1, "after": 값})
        표시 = "★" if 상태 == 200 else " "
        print(f"  {표시}[{상태}] {이름:<16} {값}")
        if 상태 != 200:
            print(f"           {본문[:200]}")
        time.sleep(0.1)
    # after 없이도 되는지
    상태, 본문, _ = 요청(session, "GET", f"{base}{스코프}/users", key, params={"limit": 1})
    print(f"  {'★' if 상태 == 200 else ' '}[{상태}] after 없음")
    if 상태 == 200:
        print(f"           {본문[:200]}")
    print()

    # ── 3. logs 엔드포인트에 conversation 관련 추가 파라미터 ─────────
    print("── 3. /logs 에 대화용 파라미터가 따로 있는가 " + "─" * 27)
    for 파라미터 in ({"include_content": "true"}, {"content": "true"},
                    {"log_type": "conversation"}, {"category": "conversation"},
                    {"type": "CONVERSATION"}):
        상태, 본문, _ = 요청(session, "GET", f"{base}{스코프}/logs", key,
                           params={"limit": 1, "event_type": "AUDIT_LOG",
                                   "after": 기본after, **파라미터})
        print(f"  [{상태}] {파라미터}")
        if 상태 != 200:
            print(f"        {본문[:200]}")
        time.sleep(0.1)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
