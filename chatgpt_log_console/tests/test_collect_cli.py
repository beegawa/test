"""스케줄러용 헤드리스 수집기 (collect.py)."""

import json

import pytest
from conftest import jsonl

import collect as collect_cli
import keystore
import settings
from compliance import ComplianceClient
from store import LogStore


@pytest.fixture
def 환경(tmp_path, monkeypatch, session):
    monkeypatch.setenv("CHATGPT_LOG_NO_KEYRING", "1")
    monkeypatch.delenv("CHATGPT_ADMIN_KEY", raising=False)
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    monkeypatch.setattr(keystore, "DATA_DIR", tmp_path)
    monkeypatch.setattr(collect_cli, "DATA_DIR", tmp_path)
    monkeypatch.setattr(
        collect_cli, "ComplianceClient",
        lambda key: ComplianceClient(key, base_url="https://example.test", workspace_id="ws_1",
                                     org_id=None, session=session, sleep=lambda _s: None),
    )
    return tmp_path


def test_키가_없으면_안내하고_종료코드_2(환경, capsys):
    assert collect_cli.main(["--db", str(환경 / "logs.db")]) == 2


def test_증분_수집해서_DB_에_쌓는다(환경, session, capsys):
    keystore.save_key("sk-admin-1234567890")
    session.event_types_ok = {"AUDIT_LOG"}
    session.pages = [{"data": [{"id": "log_1"}], "has_more": False,
                      "last_end_time": "2026-09-17T00:00:00Z"}]
    session.logs["log_1"] = jsonl({"id": "e1", "created_at": "2026-09-16T00:00:00Z",
                                   "user_email": "a@x.com", "content": "안녕"})
    db = 환경 / "logs.db"

    assert collect_cli.main(["--db", str(db), "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["result"]["saved"] == 1
    assert payload["stats"]["total"] == 1
    with LogStore(db) as store:
        assert store.get_cursor("AUDIT_LOG") == "2026-09-17T00:00:00Z"


def test_두_번_돌려도_중복_없이_누적된다(환경, session):
    keystore.save_key("sk-admin-1234567890")
    session.event_types_ok = {"AUDIT_LOG"}
    db = 환경 / "logs.db"
    for _ in range(2):
        session.pages = [{"data": [{"id": "log_1"}], "has_more": False,
                          "last_end_time": "2026-09-17T00:00:00Z"}]
        session.logs["log_1"] = jsonl({"id": "e1", "content": "안녕"})
        assert collect_cli.main(["--db", str(db), "-q"]) == 0
    with LogStore(db) as store:
        assert store.stats()["total"] == 1


def test_다운로드_오류가_있으면_종료코드_1(환경, session):
    keystore.save_key("sk-admin-1234567890")
    session.event_types_ok = {"AUDIT_LOG"}
    session.pages = [{"data": [{"id": "없는로그"}], "has_more": False,
                      "last_end_time": "2026-09-17T00:00:00Z"}]
    assert collect_cli.main(["--db", str(환경 / "logs.db"), "-q"]) == 1
