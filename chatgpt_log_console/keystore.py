"""관리자 키 보관.

  1순위: OS 자격 증명 저장소(Windows 자격 증명 관리자 / macOS 키체인 / Secret Service)
  2순위: keyring 백엔드가 없으면 사용자 홈에 소유자 전용(0600) 파일

키는 코드·설정 파일·로그 어디에도 남기지 않는다. 화면에 보여줄 일이 있으면
mask() 로 가린 값만 쓴다.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from settings import DATA_DIR, KEYRING_SERVICE, KEYRING_USERNAME

log = logging.getLogger(__name__)

_FALLBACK_NAME = "admin_key.json"


def _fallback_path() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        DATA_DIR.chmod(0o700)
    except OSError:  # pragma: no cover
        pass
    return DATA_DIR / _FALLBACK_NAME


def _keyring():
    """쓸 수 있는 keyring 모듈을 돌려준다. 없으면 None."""
    try:
        import keyring
        from keyring.backends.fail import Keyring as FailKeyring
    except Exception:  # pragma: no cover - keyring 미설치 환경
        return None
    if os.environ.get("CHATGPT_LOG_NO_KEYRING"):
        return None
    try:
        if isinstance(keyring.get_keyring(), FailKeyring):
            return None
    except Exception:  # pragma: no cover
        return None
    return keyring


def save_key(key: str) -> str:
    """키를 저장하고 어디에 저장했는지('keyring' | 'file')를 돌려준다."""
    key = (key or "").strip()
    if not key:
        raise ValueError("빈 키는 저장할 수 없습니다.")

    ring = _keyring()
    if ring is not None:
        try:
            ring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, key)
            _delete_fallback()
            return "keyring"
        except Exception as exc:  # pragma: no cover - 백엔드 오류 시 파일로 대체
            log.warning("자격 증명 저장소에 저장하지 못해 파일로 대체합니다: %s", type(exc).__name__)

    path = _fallback_path()
    # 먼저 0600 으로 만든 뒤 쓴다(다른 사용자가 읽을 틈을 주지 않기 위해).
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump({"admin_key": key}, handle)
    return "file"


def load_key() -> str | None:
    """저장된 키를 돌려준다. 환경변수 CHATGPT_ADMIN_KEY 가 있으면 그것을 우선한다."""
    env = os.environ.get("CHATGPT_ADMIN_KEY")
    if env and env.strip():
        return env.strip()

    ring = _keyring()
    if ring is not None:
        try:
            value = ring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
            if value:
                return value
        except Exception:  # pragma: no cover
            pass

    path = _fallback_path()
    if path.is_file():
        try:
            return (json.loads(path.read_text(encoding="utf-8")) or {}).get("admin_key")
        except (OSError, json.JSONDecodeError):
            return None
    return None


def _delete_fallback() -> bool:
    path = _fallback_path()
    if path.is_file():
        path.unlink()
        return True
    return False


def forget_key() -> bool:
    """저장된 키를 지운다. 지운 게 있으면 True."""
    removed = False
    ring = _keyring()
    if ring is not None:
        try:
            if ring.get_password(KEYRING_SERVICE, KEYRING_USERNAME):
                ring.delete_password(KEYRING_SERVICE, KEYRING_USERNAME)
                removed = True
        except Exception:  # pragma: no cover
            pass
    return _delete_fallback() or removed


def where() -> str | None:
    """키가 저장된 위치를 알려준다. 없으면 None."""
    if os.environ.get("CHATGPT_ADMIN_KEY", "").strip():
        return "env"
    ring = _keyring()
    if ring is not None:
        try:
            if ring.get_password(KEYRING_SERVICE, KEYRING_USERNAME):
                return "keyring"
        except Exception:  # pragma: no cover
            pass
    return "file" if _fallback_path().is_file() else None


def mask(key: str | None) -> str:
    """로그·화면에 쓸 가린 값. 예: sk-ad...4f21"""
    if not key:
        return ""
    if len(key) <= 10:
        return "*" * len(key)
    return f"{key[:5]}...{key[-4:]}"
