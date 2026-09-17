"""대화 내용만 받아서 엑셀로 바로 내보낸다.

웹 화면에 들어갈 필요 없이 더블클릭 한 번으로:
  수집 → DB 누적 → 대화만 골라 엑셀 저장 → 파일 열기

  python export_conversations.py                 # 최근 30일 대화를 엑셀로
  python export_conversations.py --days 7
  python export_conversations.py --user hong@shinwon.com
  python export_conversations.py --all           # 대화 말고 모든 로그도 함께
  python export_conversations.py --no-open       # 파일만 만들고 열지 않음
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import keystore  # noqa: E402
from collector import collect  # noqa: E402
from compliance import ComplianceClient, ComplianceError  # noqa: E402
from records import PARSER_VERSION, normalize  # noqa: E402
from settings import DEFAULT_MAX_LOGS, RETENTION_DAYS, db_path  # noqa: E402
from store import LogStore  # noqa: E402
from xlsx_export import build_workbook_bytes  # noqa: E402

log = logging.getLogger("export")
대화이벤트 = "CONVERSATION_MESSAGE"


def 기본_저장위치() -> Path:
    """바탕화면이 있으면 거기에, 없으면 현재 폴더에."""
    for 후보 in (Path.home() / "Desktop", Path.home() / "바탕 화면", Path.home()):
        if 후보.is_dir():
            return 후보
    return Path.cwd()


def 열기(path: Path) -> None:
    try:
        if os.name == "nt":
            os.startfile(str(path))  # noqa: S606  # 윈도우 기본 프로그램으로 열기
        elif sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False)
        else:
            subprocess.run(["xdg-open", str(path)], check=False)
    except OSError as exc:  # pragma: no cover
        log.warning("파일을 자동으로 열지 못했습니다: %s", exc)


def 대화순_정렬(행들: list[dict]) -> list[dict]:
    """같은 대화끼리 모으고, 그 안에서는 시간 순으로 둔다.

    엑셀에서 질문과 답변이 붙어 있어야 읽을 수 있다.
    """
    def 열쇠(행):
        return (행.get("conversation_id") or "~없음", 행.get("ts") or "", 행.get("id") or "")
    return sorted(행들, key=열쇠)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="대화 내용을 받아 엑셀로 내보내기")
    parser.add_argument("--days", type=int, default=RETENTION_DAYS,
                        help=f"최근 며칠치 (기본 {RETENTION_DAYS}일 = 보관 한계)")
    parser.add_argument("--user", help="이 사용자만 (이메일 일부)")
    parser.add_argument("--q", help="이 키워드가 든 대화만")
    parser.add_argument("--all", action="store_true", help="대화 외의 로그도 함께 내보낸다")
    parser.add_argument("--skip-pull", action="store_true", help="새로 받지 않고 DB 내용만 내보낸다")
    parser.add_argument("--out", help="저장할 폴더 (기본: 바탕화면)")
    parser.add_argument("--db", help="SQLite 파일 경로")
    parser.add_argument("--no-open", action="store_true", help="다 만든 뒤 열지 않는다")
    parser.add_argument("-q", "--quiet", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="  %(message)s",
    )

    key = keystore.load_key()
    if not key:
        print()
        print("  저장된 관리자 키가 없습니다.")
        print("  시작_Windows.bat 을 한 번 실행해 웹 화면에서 키를 저장한 뒤 다시 실행하세요.")
        print()
        return 2

    with LogStore(args.db or db_path()) as store:
        store.ensure_parsed(normalize, PARSER_VERSION)

        if not args.skip_pull:
            print()
            print(f"  최근 {args.days}일치를 받는 중입니다. 잠시 기다려 주세요…")
            try:
                결과 = collect(
                    ComplianceClient(key), store,
                    days=args.days,
                    event_types=None if args.all else [대화이벤트],
                    max_logs=DEFAULT_MAX_LOGS,
                )
            except ComplianceError as exc:
                print()
                print(f"  받아오지 못했습니다: {exc}")
                print()
                return 1
            print(f"  다운로드 {결과.fetched}건 · 새로 저장 {결과.saved}건"
                  f" · 이미 있던 것 {max(결과.records - 결과.saved, 0)}건")
            if 결과.errors:
                print(f"  (오류 {len(결과.errors)}건 - 자세한 내용은 로그를 보세요)")

        조건 = {"user": args.user, "keyword": args.q}
        if not args.all:
            조건["event_type"] = 대화이벤트
        행들 = 대화순_정렬(store.search(**조건, limit=1_000_000))
        통계 = store.stats()

    if not 행들:
        print()
        print("  내보낼 대화가 없습니다.")
        print(f"  (DB 에는 모두 {통계['total']}건이 있습니다. --all 로 다른 로그도 볼 수 있습니다.)")
        print()
        return 1

    이름 = "ChatGPT_로그" if args.all else "ChatGPT_대화"
    파일 = Path(args.out or 기본_저장위치()) / f"{이름}_{datetime.now():%Y%m%d_%H%M}.xlsx"
    파일.parent.mkdir(parents=True, exist_ok=True)
    파일.write_bytes(build_workbook_bytes(행들, sheet_title="대화" if not args.all else "로그"))
    try:
        파일.chmod(0o600)          # 대화 내용이 담긴다
    except OSError:                # pragma: no cover
        pass

    대화수 = len({행.get("conversation_id") for 행 in 행들 if 행.get("conversation_id")})
    사람수 = len({행.get("user") for 행 in 행들 if 행.get("user")})
    print()
    print(f"  엑셀로 저장했습니다: {파일}")
    print(f"  메시지 {len(행들):,}건 · 대화 {대화수:,}개 · 사용자 {사람수}명")
    print(f"  (DB 누적 {통계['total']:,}건 · {통계['oldest'][:10]} ~ {통계['newest'][:10]})")
    print()

    if not args.no_open:
        열기(파일)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
