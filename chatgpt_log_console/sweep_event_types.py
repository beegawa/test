"""event_type 이름 일괄 탐색기.

대화 로그의 event_type 이름을 문서에서 찾을 수 없어, 그럴듯한 이름을 한 번에
훑어보고 **어떤 응답이 오는지** 로 판별한다.

  정상(200)              → 바로 쓸 수 있는 이름
  "Invalid event_type"   → 그런 이름이 없음
  그 밖의 오류(403 등)   → ★ 이름은 맞는데 권한이 없다는 뜻. 가장 중요한 단서.

  python sweep_event_types.py --key sk-admin-...
  python sweep_event_types.py --extra MY_NAME --extra OTHER_NAME
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import requests  # noqa: E402

import keystore  # noqa: E402
from compliance import since_days  # noqa: E402
from settings import BASE_URL, ORG_ID, RETENTION_DAYS, WORKSPACE_ID  # noqa: E402

# 공식 안내의 로그 종류(Conversation / Codex / Codex Security / Audit / App / Auth /
# App Auth)와 AUTH_LOG 의 작명 규칙을 바탕으로 넓게 깔아 본다.
후보들 = [
    # 대화 내용
    "CONVERSATION_LOG", "CONVERSATIONS_LOG", "CONVERSATION", "CONVERSATIONS",
    "CONVERSATION_CONTENT_LOG", "CONTENT_LOG", "CHAT_LOG", "CHATS_LOG", "CHAT",
    "MESSAGE_LOG", "MESSAGES_LOG", "MESSAGE", "THREAD_LOG", "THREADS_LOG",
    "CHATGPT_LOG", "GPT_LOG", "PROMPT_LOG", "COMPLETION_LOG",
    # 공식 안내에 나오는 나머지 종류
    "CODEX_LOG", "CODEX_SECURITY_LOG", "CODEX_USAGE_LOG",
    "AUDIT_LOG", "ADMIN_AUDIT_LOG", "ADMIN_LOG",
    "APP_LOG", "APPS_LOG", "APP_AUTH_LOG",
    "AUTH_LOG",
    # 그 밖에 있을 법한 것
    "FILE_LOG", "FILES_LOG", "UPLOAD_LOG", "MEMORY_LOG", "PROJECT_LOG",
    "GPTS_LOG", "AGENT_LOG", "TOOL_LOG", "SEARCH_LOG", "CONNECTOR_LOG",
    "USER_LOG", "WORKSPACE_LOG", "ORG_LOG", "USAGE_LOG", "ACTIVITY_LOG",
    "EVENT_LOG", "COMPLIANCE_LOG", "DLP_LOG",
    # 대소문자 규칙이 다를 가능성
    "conversation_log", "conversation", "ConversationLog",
]

없는이름표시 = "invalid event_type"


def 한번(session, url, key, 이벤트, after, timeout=30):
    try:
        response = session.get(
            url,
            headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
            params={"limit": 1, "event_type": 이벤트, "after": after},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        return None, f"연결 실패: {type(exc).__name__}"
    본문 = (response.text or "").strip().replace("\n", " ")
    return response.status_code, 본문[:300]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="event_type 이름 일괄 탐색")
    parser.add_argument("--key", help="관리자 키 (생략하면 저장된 키)")
    parser.add_argument("--workspace", default=WORKSPACE_ID)
    parser.add_argument("--org", default=ORG_ID)
    parser.add_argument("--base", default=BASE_URL)
    parser.add_argument("--extra", action="append", default=[],
                        help="직접 시험해 볼 이름 (여러 번 지정 가능)")
    parser.add_argument("--delay", type=float, default=0.15,
                        help="요청 사이 간격(초). 레이트리밋이 걸리면 늘리세요")
    args = parser.parse_args(argv)

    key = args.key or keystore.load_key()
    if not key:
        print("저장된 키가 없습니다. --key 로 넣거나 웹 화면에서 먼저 저장하세요.")
        return 2

    스코프 = f"/organizations/{args.org}" if args.org else f"/workspaces/{args.workspace}"
    url = f"{args.base.rstrip('/')}{스코프}/logs"
    after = since_days(RETENTION_DAYS)
    이름들 = args.extra + [n for n in 후보들 if n not in args.extra]

    print()
    print("=" * 74)
    print("  event_type 이름 일괄 탐색")
    print("=" * 74)
    print(f"  키   : {keystore.mask(key)}")
    print(f"  주소 : {url}")
    print(f"  시험할 이름 {len(이름들)}개")
    print()

    성공, 없음, 특이 = [], [], []
    session = requests.Session()
    for 번호, 이름 in enumerate(이름들, 1):
        상태, 본문 = 한번(session, url, key, 이름, after)
        if 상태 == 200:
            성공.append((이름, 본문))
            print(f"  [{번호:>2}/{len(이름들)}] ★ 정상  {이름}")
        elif 상태 == 400 and 없는이름표시 in 본문.lower():
            없음.append(이름)
            print(f"  [{번호:>2}/{len(이름들)}]   없음  {이름}")
        else:
            특이.append((이름, 상태, 본문))
            print(f"  [{번호:>2}/{len(이름들)}] ▲ {상태}  {이름}")
            print(f"              → {본문}")
        time.sleep(args.delay)

    print()
    print("── 결과 " + "─" * 64)
    if 성공:
        print("  ★ 바로 쓸 수 있는 이름:")
        for 이름, 본문 in 성공:
            print(f"     {이름}   {본문[:120]}")
    else:
        print("  ★ 정상 응답한 이름이 없습니다.")
    if 특이:
        print()
        print("  ▲ '없는 이름' 이 아닌 다른 응답 - 이름은 맞는데 권한이 없을 수 있습니다:")
        for 이름, 상태, 본문 in 특이:
            print(f"     [{상태}] {이름}")
            print(f"            {본문[:200]}")
    print()
    print(f"  (그런 이름 없음: {len(없음)}개)")
    if 성공:
        이름목록 = ",".join(이름 for 이름, _ in 성공)
        print()
        print("  이 이름들로 프로그램을 돌리려면:")
        print(f"     set CHATGPT_EVENT_TYPES={이름목록}")
        print("     py -3 app.py")
    print()
    return 0 if 성공 else 1


if __name__ == "__main__":
    raise SystemExit(main())
