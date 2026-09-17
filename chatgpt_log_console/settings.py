"""chatgpt_log_console 기본 설정값.

값은 모두 환경변수로 덮어쓸 수 있다. 관리자 키만은 여기에 두지 않는다
(키는 keystore.py 가 OS 자격 증명 저장소에 보관한다).
"""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "chatgpt-log-console"
KEYRING_SERVICE = "chatgpt-log-console"
KEYRING_USERNAME = "admin-key"

# ------------------------------------------------------------------ API
BASE_URL = os.environ.get(
    "CHATGPT_COMPLIANCE_BASE_URL", "https://api.chatgpt.com/v1/compliance"
).rstrip("/")

# ShinwonChatGPT 워크스페이스
WORKSPACE_ID = os.environ.get(
    "CHATGPT_WORKSPACE_ID", "f4fd05b9-c4ef-4fbf-8d31-e33dcdb44319"
)
# 조직 스코프로 받고 싶을 때만 지정한다(워크스페이스보다 우선).
ORG_ID = os.environ.get("CHATGPT_ORG_ID") or None

# 대화 로그의 정확한 event_type 이름은 관리자 콘솔의 '관리자 API 문서'에서
# 확인해야 한다. 확인 전까지는 아래 후보를 limit=1 로 찔러보고 200 인 것만 쓴다.
# 정확한 이름을 알게 되면 이 목록 맨 앞에 추가할 것.
# 공식 안내에 나오는 로그 종류: Conversation / Codex / Codex Security / Audit /
# App / Auth / App Auth. 확인된 실제 값은 AUTH_LOG 뿐이라 같은 규칙(<이름>_LOG)으로
# 후보를 넓혀 둔다. diagnose.py 로 어떤 값이 통하는지 확인할 수 있다.
_DEFAULT_EVENT_TYPES = [
    # 실제 워크스페이스에서 200 을 받은 것들 (2026-09 확인)
    "AUDIT_LOG",
    "AUTH_LOG",
    "APP_LOG",
    "APP_AUTH_LOG",
    "CODEX_LOG",
    "CODEX_SECURITY_LOG",
    # 대화 내용 로그의 이름은 아직 확정되지 않았다.
    # CONVERSATION_LOG / CHAT_LOG / MESSAGE_LOG 는 "Invalid event_type" 으로 거절됐다.
    # sweep_event_types.py 와 explore_api.py 로 계속 찾는 중.
]

# 정확한 이름을 알아내면 코드를 고치지 않고도 쓸 수 있게 환경변수로 덮어쓸 수 있다.
#   CHATGPT_EVENT_TYPES=CONVERSATION_LOG,AUTH_LOG
EVENT_TYPE_CANDIDATES = [
    name.strip()
    for name in os.environ.get("CHATGPT_EVENT_TYPES", ",".join(_DEFAULT_EVENT_TYPES)).split(",")
    if name.strip()
]

# ------------------------------------------------------------------ 저장소
# 대화 내용(개인정보 가능)이 담기므로 저장소는 사용자 홈 아래 소유자 전용 폴더에 둔다.
DATA_DIR = Path(
    os.environ.get("CHATGPT_LOG_DATA_DIR", Path.home() / ".chatgpt_log_console")
).expanduser()
DB_FILENAME = "chatgpt_logs.db"

# ------------------------------------------------------------------ 동작값
PAGE_LIMIT = int(os.environ.get("CHATGPT_LOG_PAGE_LIMIT", "100"))
HTTP_TIMEOUT = int(os.environ.get("CHATGPT_LOG_HTTP_TIMEOUT", "30"))
MAX_RETRIES = int(os.environ.get("CHATGPT_LOG_MAX_RETRIES", "5"))
PREVIEW_LIMIT = 500          # 화면 미리보기 최대 건수 (전체는 엑셀로)
DEFAULT_MAX_LOGS = 20000     # 한 번의 수집에서 내려받을 로그 상한(사고 방지)
RETENTION_DAYS = 30          # API 로그 보관 기간 - 이보다 오래된 건 받을 수 없다


def db_path() -> Path:
    """SQLite 파일 경로. 폴더가 없으면 소유자 전용으로 만든다."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        DATA_DIR.chmod(0o700)
    except OSError:  # pragma: no cover - 윈도우 등에서는 무시
        pass
    return DATA_DIR / DB_FILENAME
