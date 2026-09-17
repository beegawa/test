"""관리자 키 진단 도구.

'검증이 안 된다' 고 할 때 원인을 좁히기 위해, 여러 주소 조합을 하나씩 찔러보고
각각의 HTTP 상태와 서버가 보낸 설명을 그대로 보여준다.

  python diagnose.py                 # 저장된 키로 진단
  python diagnose.py --key sk-...    # 키를 직접 넣어 진단 (저장하지 않음)
  python diagnose.py --org org_...   # 조직 스코프도 같이 시험

출력에는 키가 찍히지 않는다(앞 5자리/뒤 4자리만).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import requests  # noqa: E402

import keystore  # noqa: E402
from settings import (  # noqa: E402
    BASE_URL,
    EVENT_TYPE_CANDIDATES,
    ORG_ID,
    RETENTION_DAYS,
    WORKSPACE_ID,
)
from compliance import since_days  # noqa: E402


def 찔러보기(session, url: str, key: str, params: dict, *, 원본=False):
    """한 번 호출하고 (상태코드, 설명) 을 돌려준다. 원본=True 면 응답 본문 전체도 함께."""
    try:
        response = session.get(
            url,
            headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
            params=params,
            timeout=30,
        )
    except requests.RequestException as exc:
        메시지 = f"연결 자체가 안 됨: {type(exc).__name__}: {exc}"
        return (None, 메시지, "") if 원본 else (None, 메시지)

    설명 = ""
    try:
        body = response.json()
        if isinstance(body, dict):
            error = body.get("error")
            설명 = (error.get("message") if isinstance(error, dict) else error) or ""
            if not 설명 and "data" in body:
                설명 = f"정상 - data {len(body.get('data') or [])}건, has_more={body.get('has_more')}"
    except ValueError:
        설명 = (response.text or "")[:400].replace("\n", " ")
    설명 = 설명 or (response.text or "")[:400].replace("\n", " ")
    if 원본:
        return response.status_code, 설명, (response.text or "")
    return response.status_code, 설명


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="관리자 키 진단")
    parser.add_argument("--key", help="시험할 키 (생략하면 저장된 키)")
    parser.add_argument("--workspace", default=WORKSPACE_ID, help="워크스페이스 ID")
    parser.add_argument("--org", default=ORG_ID, help="조직 ID (알고 있다면)")
    parser.add_argument("--base", default=BASE_URL, help="API 기본 주소")
    parser.add_argument("--event-type", action="append",
                        help="이 이름만 시험한다 (여러 번 지정 가능)")
    parser.add_argument("--quick", action="store_true",
                        help="키·이름 확인만 하고 추가 탐색은 건너뛴다")
    args = parser.parse_args(argv)

    key = args.key or keystore.load_key()
    if not key:
        print("저장된 키가 없습니다. --key 로 직접 넣거나 웹 화면에서 먼저 저장하세요.")
        return 2

    print()
    print("=" * 74)
    print("  관리자 키 진단")
    print("=" * 74)
    print(f"  키        : {keystore.mask(key)}  (길이 {len(key)}자, 앞부분 '{key[:8]}…')")
    print(f"  기본 주소 : {args.base}")
    print(f"  워크스페이스: {args.workspace}")
    print(f"  조직      : {args.org or '(지정 안 함)'}")
    print()

    session = requests.Session()
    후보: list[tuple[str, str]] = []
    if args.workspace:
        후보.append(("워크스페이스 스코프", f"{args.base}/workspaces/{args.workspace}/logs"))
    if args.org:
        후보.append(("조직 스코프", f"{args.base}/organizations/{args.org}/logs"))

    # 이 API 는 event_type 과 after 를 필수로 요구한다(빠지면 422).
    after = since_days(RETENTION_DAYS)
    성공한주소 = None
    print("── 1. 어느 주소가 통하는가 " + "─" * 46)
    print(f"  (필수 파라미터 after = {after} 로 시험합니다)")
    for 이름, url in 후보:
        결과 = []
        for 이벤트 in (args.event_type or EVENT_TYPE_CANDIDATES):
            status, 설명 = 찔러보기(
                session, url, key, {"limit": 1, "event_type": 이벤트, "after": after}
            )
            결과.append((status, 이벤트, 설명))
            if status == 200:
                break
            if status in (401, 403, 404) or status is None:
                break        # 키/주소 문제면 다른 event_type 을 봐도 의미가 없다
        status, 이벤트, 설명 = 결과[-1]
        표시 = "정상" if status == 200 else str(status)
        print(f"  [{표시:>4}] {이름}  (event_type={이벤트})")
        print(f"         {url}")
        print(f"         → {설명}")
        if status == 200 and 성공한주소 is None:
            성공한주소 = url
    print()

    if 성공한주소 is None:
        print("── 무엇을 확인해야 하나 " + "─" * 48)
        print("  401 → 관리자 콘솔 > 인증 정보 > '관리자 키' 에서 발급한 키인지 확인하세요.")
        print("        일반 API 키(sk-proj-…)로는 이 API 를 쓸 수 없습니다.")
        print("  403 → 그 키에 '규정 준수 로깅 플랫폼(Compliance Logs Platform)' 읽기")
        print("        권한이 있는지 확인하세요.")
        print("  404 → 워크스페이스/조직 ID 가 맞는지 확인하세요.")
        print("  422 → 필수 파라미터(event_type, after)가 빠졌습니다. 프로그램 버그이니 알려주세요.")
        print("  연결 실패 → 회사 방화벽/프록시가 api.chatgpt.com 을 막고 있을 수 있습니다.")
        print()
        return 1

    print("── 2. 어떤 event_type 이 통하는가 " + "─" * 39)
    통과 = []
    for 이름 in (args.event_type or EVENT_TYPE_CANDIDATES):
        status, 설명 = 찔러보기(
            session, 성공한주소, key, {"limit": 1, "event_type": 이름, "after": after}
        )
        표시 = "정상" if status == 200 else str(status)
        print(f"  [{표시:>4}] {이름:<20} {설명}")
        if status == 200:
            통과.append(이름)
    print()
    print("── 3. 서버에 허용되는 event_type 을 직접 물어보기 " + "─" * 22)
    print("  (일부러 없는 값을 보내면 API 가 허용 목록을 알려주는 경우가 있습니다)")
    상태, _설명, 본문 = 찔러보기(
        session, 성공한주소, key,
        {"limit": 1, "event_type": "__SHOW_ALLOWED_VALUES__", "after": after},
        원본=True,
    )
    print(f"  [{상태}] 서버가 보낸 응답 전체:")
    print("  " + "-" * 70)
    for 줄 in (본문 or "(본문 없음)").splitlines() or ["(빈 응답)"]:
        for i in range(0, len(줄), 100):
            print("  " + 줄[i:i + 100])
    print("  " + "-" * 70)
    print()
    print("── 결과 " + "─" * 64)
    print(f"  쓸 수 있는 주소      : {성공한주소}")
    print(f"  쓸 수 있는 event_type: {', '.join(통과) if 통과 else '(없음 - 필터 없이 전체 수집)'}")
    print()

    # 대화 로그의 이름을 아직 못 찾았다면, 이어서 더 넓게 훑는다.
    # (따로 실행하는 걸 잊기 쉬워서 여기서 바로 이어 돌린다. --quick 으로 생략)
    if not args.quick:
        인자 = ["--key", key, "--workspace", args.workspace, "--base", args.base]
        if args.org:
            인자 += ["--org", args.org]

        import explore_api
        import probe_conversations
        import sweep_event_types

        explore_api.main(인자)
        probe_conversations.main(인자)
        sweep_event_types.main(인자)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
