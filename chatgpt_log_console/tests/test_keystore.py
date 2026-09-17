"""관리자 키 보관 - keyring 이 없을 때의 파일 대체 경로."""

import json
import os
import stat

import pytest

import keystore
import settings


@pytest.fixture
def 파일보관(tmp_path, monkeypatch):
    """keyring 을 끄고 저장 폴더를 임시 폴더로 돌린다."""
    monkeypatch.setenv("CHATGPT_LOG_NO_KEYRING", "1")
    monkeypatch.delenv("CHATGPT_ADMIN_KEY", raising=False)
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    monkeypatch.setattr(keystore, "DATA_DIR", tmp_path)
    return tmp_path


def test_저장하고_다시_읽는다(파일보관):
    assert keystore.save_key("sk-admin-1234567890") == "file"
    assert keystore.load_key() == "sk-admin-1234567890"
    assert keystore.where() == "file"


def test_키_파일은_소유자만_읽을_수_있다(파일보관):
    keystore.save_key("sk-admin-1234567890")
    mode = stat.S_IMODE(os.stat(파일보관 / "admin_key.json").st_mode)
    assert oct(mode) == "0o600"


def test_삭제하면_남지_않는다(파일보관):
    keystore.save_key("sk-admin-1234567890")
    assert keystore.forget_key() is True
    assert keystore.load_key() is None
    assert keystore.where() is None
    assert keystore.forget_key() is False


def test_환경변수가_있으면_그것을_먼저_쓴다(파일보관, monkeypatch):
    keystore.save_key("저장된키1234567890")
    monkeypatch.setenv("CHATGPT_ADMIN_KEY", "환경변수키")
    assert keystore.load_key() == "환경변수키"
    assert keystore.where() == "env"


def test_빈_키는_저장하지_않는다(파일보관):
    with pytest.raises(ValueError):
        keystore.save_key("   ")


def test_가린_값에는_키_본문이_드러나지_않는다():
    masked = keystore.mask("sk-admin-abcdefghijklmn")
    assert masked == "sk-ad...klmn"
    assert "abcdefghij" not in masked
    assert keystore.mask(None) == ""
    assert keystore.mask("짧은키") == "***"


def test_저장_파일에는_키_외의_것이_들어가지_않는다(파일보관):
    keystore.save_key("sk-admin-1234567890")
    saved = json.loads((파일보관 / "admin_key.json").read_text(encoding="utf-8"))
    assert list(saved) == ["admin_key"]
