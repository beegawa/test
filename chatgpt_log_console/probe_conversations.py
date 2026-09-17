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

    # ── 4. 확보한 conversation_id 로 개별 조회 ──────────────────────
    # 폐기된 것은 '목록(list) 조회' 뿐이다. 개별 대화 조회는 살아 있을 수 있고,
    # conversation_id 는 AUDIT_LOG / APP_LOG 안에 들어 있다.
    print("── 4. 실제 conversation_id 로 개별 조회가 되는가 " + "─" * 23)
    대화ids, 사용자ids = 대화id_모으기(session, base, 스코프, key, 기본after)
    if not 대화ids:
        print("  로그에서 conversation_id 를 찾지 못했습니다.")
    for 대화id in 대화ids[:2]:
        print(f"\n  ● conversation_id = {대화id}")
        for 꼴 in ("/conversations/{id}", "/conversations/{id}/messages",
                   "/conversations/{id}/logs", "/conversations/{id}/transcript",
                   "/logs/{id}", "/conversation/{id}"):
            뒤 = 꼴.format(id=대화id)
            상태, 본문, 헤더 = 요청(session, "GET", f"{base}{스코프}{뒤}", key)
            allow = 헤더.get("Allow") or 헤더.get("allow") or ""
            if 상태 == 404 and not allow:
                print(f"     [404] {꼴}")
                continue
            표시 = "★" if 상태 == 200 else " "
            print(f"    {표시}[{상태}] {꼴} {('Allow: ' + allow) if allow else ''}")
            print(f"           {본문[:300]}")
            time.sleep(0.1)
    for 사용자id in 사용자ids[:1]:
        print(f"\n  ● user_id = {사용자id}")
        for 꼴 in ("/users/{id}/conversations", "/users/{id}/logs", "/users/{id}"):
            뒤 = 꼴.format(id=사용자id)
            상태, 본문, _ = 요청(session, "GET", f"{base}{스코프}{뒤}", key)
            표시 = "★" if 상태 == 200 else " "
            print(f"    {표시}[{상태}] {꼴}")
            if 상태 != 404:
                print(f"           {본문[:300]}")
            time.sleep(0.1)
    print()
    return 0


def 대화id_모으기(session, base, 스코프, key, after, 최대=3):
    """AUDIT_LOG / APP_LOG 를 받아 그 안의 conversation_id 와 user_id 를 뽑는다."""
    대화, 사용자 = [], []
    for 이벤트 in ("APP_LOG", "AUDIT_LOG"):
        상태, 본문, _ = 요청(session, "GET", f"{base}{스코프}/logs", key,
                           params={"limit": 3, "event_type": 이벤트, "after": after})
        if 상태 != 200:
            continue
        try:
            목록 = (json.loads(본문) or {}).get("data") or []
        except json.JSONDecodeError:
            continue
        for 항목 in 목록:
            로그id = 항목.get("id")
            if not 로그id:
                continue
            상태2, 본문2, _ = 요청(session, "GET", f"{base}{스코프}/logs/{로그id}", key)
            if 상태2 != 200:
                continue
            for 줄 in 본문2.split("} {"):        # 줄바꿈이 공백으로 바뀌어 있을 수 있다
                for 조각 in (줄, "{" + 줄, 줄 + "}"):
                    try:
                        레코드 = json.loads(조각)
                    except (json.JSONDecodeError, TypeError):
                        continue
                    _훑기(레코드, 대화, 사용자)
                    break
            if len(대화) >= 최대:
                break
        if len(대화) >= 최대:
            break
    return 대화, 사용자


def _훑기(값, 대화, 사용자, 깊이=0):
    if 깊이 > 4 or not isinstance(값, dict):
        return
    for 키, 하위 in 값.items():
        if 키 == "conversation_id" and 하위 and 하위 not in 대화:
            대화.append(하위)
        if 키 == "user_id" and 하위 and 하위 not in 사용자:
            사용자.append(하위)
        if isinstance(하위, dict):
            _훑기(하위, 대화, 사용자, 깊이 + 1)
        elif isinstance(하위, list):
            for 항목 in 하위:
                _훑기(항목, 대화, 사용자, 깊이 + 1)


if __name__ == "__main__":
    raise SystemExit(main())
