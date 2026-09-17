"""대화 로그가 어디 있는지 찾는 탐색 도구.

event_type 후보로는 대화 로그를 못 찾았다(Conversation 만 빠짐). 그래서 범위를
넓혀 세 가지를 확인한다.

  1. API 스키마(openapi.json 등)  - 있으면 유효한 event_type 목록이 통째로 나온다
  2. 다른 엔드포인트 경로         - 예전 Compliance API 는 /conversations 를 썼다
  3. 실제 로그 한 건의 속 내용     - 지금 받을 수 있는 로그에 대화가 들어 있는지

  python explore_api.py --key sk-admin-...
  python explore_api.py --key ... --no-peek     # 3번(내용 들여다보기) 생략
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import requests  # noqa: E402

import keystore  # noqa: E402
from compliance import since_days  # noqa: E402
from settings import BASE_URL, ORG_ID, RETENTION_DAYS, WORKSPACE_ID  # noqa: E402

# 지금까지 통한다고 확인된 것들
확인된_이벤트 = ["CONVERSATION_MESSAGE", "AUDIT_LOG", "AUTH_LOG", "APP_LOG", "APP_AUTH_LOG", "CODEX_LOG", "CODEX_SECURITY_LOG"]

스키마_경로 = [
    "/openapi.json", "/docs", "/redoc", "/schema", "/swagger.json",
]
탐색_경로 = [
    "/conversations", "/conversations/logs", "/messages", "/chats", "/threads",
    "/logs/types", "/log_types", "/event_types", "/types", "/logs/schema",
    "/users", "/files", "/projects", "/exports", "/",
]


def 호출(session, url, key, params=None, timeout=30, *, 원문=False):
    """원문=True 면 줄바꿈을 살린다. JSONL 은 줄 단위라 반드시 살려야 한다."""
    try:
        response = session.get(
            url,
            headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
            params=params or {},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        return None, f"연결 실패: {type(exc).__name__}"
    본문 = (response.text or "").strip()
    return response.status_code, 본문 if 원문 else 본문.replace("\n", " ")


def 줄바꿔출력(본문: str, 폭: int = 100, 최대줄: int = 12) -> None:
    줄들 = [본문[i:i + 폭] for i in range(0, min(len(본문), 폭 * 최대줄), 폭)]
    for 줄 in 줄들 or ["(빈 응답)"]:
        print("       " + 줄)
    if len(본문) > 폭 * 최대줄:
        print(f"       … (총 {len(본문)}자)")


def 구조보기(값, 깊이=0, 최대깊이=3) -> list[str]:
    """값의 '모양' 만 뽑는다. 실제 내용은 짧게 줄인다."""
    들여쓰기 = "  " * 깊이
    if 깊이 > 최대깊이:
        return [f"{들여쓰기}…"]
    if isinstance(값, dict):
        줄 = []
        for 키, 하위 in list(값.items())[:25]:
            if isinstance(하위, (dict, list)):
                줄.append(f"{들여쓰기}{키}:")
                줄 += 구조보기(하위, 깊이 + 1, 최대깊이)
            else:
                미리보기 = str(하위)
                if len(미리보기) > 70:
                    미리보기 = 미리보기[:70] + "…"
                줄.append(f"{들여쓰기}{키} = {미리보기}")
        return 줄
    if isinstance(값, list):
        if not 값:
            return [f"{들여쓰기}(빈 목록)"]
        return [f"{들여쓰기}[{len(값)}개 중 첫 번째]"] + 구조보기(값[0], 깊이 + 1, 최대깊이)
    미리보기 = str(값)
    return [f"{들여쓰기}{미리보기[:70]}"]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="대화 로그 위치 탐색")
    parser.add_argument("--key")
    parser.add_argument("--workspace", default=WORKSPACE_ID)
    parser.add_argument("--org", default=ORG_ID)
    parser.add_argument("--base", default=BASE_URL)
    parser.add_argument("--no-peek", action="store_true", help="실제 로그 내용 확인 생략")
    args = parser.parse_args(argv)

    key = args.key or keystore.load_key()
    if not key:
        print("저장된 키가 없습니다. --key 로 넣거나 웹 화면에서 먼저 저장하세요.")
        return 2

    base = args.base.rstrip("/")
    스코프 = f"/organizations/{args.org}" if args.org else f"/workspaces/{args.workspace}"
    after = since_days(RETENTION_DAYS)
    session = requests.Session()

    print()
    print("=" * 74)
    print("  대화 로그 위치 탐색")
    print("=" * 74)
    print(f"  키   : {keystore.mask(key)}")
    print(f"  스코프: {base}{스코프}")
    print()

    # ── 1. API 스키마 ────────────────────────────────────────────────
    print("── 1. API 스키마에 event_type 목록이 있는가 " + "─" * 28)
    뿌리 = base.rsplit("/compliance", 1)[0] if "/compliance" in base else base
    for 뒤 in 스키마_경로:
        for 앞 in (base, 뿌리):
            url = f"{앞}{뒤}"
            상태, 본문 = 호출(session, url, key)
            표시 = "★정상" if 상태 == 200 else str(상태)
            print(f"  [{표시:>5}] {url}")
            if 상태 == 200 and 본문:
                줄바꿔출력(본문, 최대줄=20)
    print()

    # ── 2. 다른 엔드포인트 ───────────────────────────────────────────
    print("── 2. 대화가 다른 경로에 있는가 " + "─" * 40)
    찾은경로 = []
    for 뒤 in 탐색_경로:
        url = f"{base}{스코프}{뒤}"
        상태, 본문 = 호출(session, url, key, {"limit": 1, "after": after})
        if 상태 == 404:
            print(f"  [  404] {뒤}")
            continue
        표시 = "★정상" if 상태 == 200 else str(상태)
        print(f"  [{표시:>5}] {뒤}")
        줄바꿔출력(본문, 최대줄=6)
        if 상태 == 200:
            찾은경로.append(뒤)
    print()

    # ── 3. 실제 로그 속 내용 ─────────────────────────────────────────
    if not args.no_peek:
        print("── 3. 지금 받을 수 있는 로그에 무엇이 들어 있는가 " + "─" * 23)
        print("  ※ 실제 업무 데이터입니다. 값은 70자까지만 보여줍니다.")
        for 이벤트 in 확인된_이벤트:
            상태, 본문 = 호출(session, f"{base}{스코프}/logs", key,
                            {"limit": 1, "event_type": 이벤트, "after": after})
            if 상태 != 200:
                continue
            try:
                목록 = (json.loads(본문) or {}).get("data") or []
            except json.JSONDecodeError:
                continue
            if not 목록:
                print(f"\n  ● {이벤트}: (해당 기간에 없음)")
                continue
            로그id = 목록[0].get("id")
            print(f"\n  ● {이벤트}  (로그 id: {로그id})")
            상태2, 본문2 = 호출(session, f"{base}{스코프}/logs/{로그id}", key, 원문=True)
            if 상태2 != 200:
                print(f"     다운로드 실패 [{상태2}] {본문2[:150]}")
                continue
            줄들 = [줄 for 줄 in 본문2.splitlines() if 줄.strip()]
            print(f"     JSONL {len(줄들)}줄")
            레코드 = None
            for 첫줄 in 줄들[:1]:
                try:
                    레코드 = json.loads(첫줄)
                except json.JSONDecodeError:
                    print(f"     JSON 으로 못 읽음: {첫줄[:150]}")
            if 레코드 is None:
                continue
            for 줄 in 구조보기(레코드)[:40]:
                print("     " + 줄)
        print()

    print("── 결과 " + "─" * 64)
    print(f"  통하는 추가 경로: {', '.join(찾은경로) if 찾은경로 else '(없음)'}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
