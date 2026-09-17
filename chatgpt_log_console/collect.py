"""스케줄러가 호출하는 헤드리스 증분 수집기.

API 로그 보관 기간은 30일이라, 30일 안에 한 번은 반드시 돌아야 데이터가 끊기지 않는다.
매일 1회 실행을 권장한다.

  Windows 작업 스케줄러:  pythonw.exe  <경로>\\collect.py --days 2
  cron:                    5 3 * * *  /usr/bin/python3 /경로/collect.py --days 2

키는 웹 콘솔에서 저장한 것을 그대로 쓴다(환경변수 CHATGPT_ADMIN_KEY 도 가능).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import keystore  # noqa: E402
from collector import collect  # noqa: E402
from compliance import ComplianceClient, ComplianceError  # noqa: E402
from settings import DATA_DIR, DEFAULT_MAX_LOGS, db_path  # noqa: E402
from store import LogStore  # noqa: E402

log = logging.getLogger("collect")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ChatGPT 대화 로그 증분 수집 (스케줄러용)")
    parser.add_argument("--days", type=int, default=2,
                        help="증분 커서가 없을 때 받아올 기간(일). 기본 2")
    parser.add_argument("--full", action="store_true",
                        help="증분이 아니라 --days 기간 전체를 다시 받는다")
    parser.add_argument("--event-type", action="append",
                        help="event_type 직접 지정 (여러 번 가능). 생략하면 자동 탐지")
    parser.add_argument("--max-logs", type=int, default=DEFAULT_MAX_LOGS,
                        help=f"한 번에 내려받을 로그 수 상한 (기본 {DEFAULT_MAX_LOGS})")
    parser.add_argument("--db", help="SQLite 파일 경로")
    parser.add_argument("--log-file", help="실행 로그를 남길 파일 (기본: 데이터 폴더/collect.log)")
    parser.add_argument("--json", action="store_true", help="결과를 JSON 으로 출력")
    parser.add_argument("-q", "--quiet", action="store_true", help="경고 이상만 출력")
    return parser


def _setup_logging(args) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    path = Path(args.log_file) if args.log_file else DATA_DIR / "collect.log"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(path, encoding="utf-8"))
    except OSError as exc:  # pragma: no cover
        print(f"로그 파일을 열지 못했습니다: {exc}", file=sys.stderr)
    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _setup_logging(args)

    key = keystore.load_key()
    if not key:
        log.error("저장된 관리자 키가 없습니다. 웹 콘솔(app.py)에서 먼저 키를 저장하세요.")
        return 2

    try:
        client = ComplianceClient(key)
    except ComplianceError as exc:
        log.error("%s", exc)
        return 2

    with LogStore(args.db or db_path()) as store:
        try:
            result = collect(
                client,
                store,
                days=args.days,
                incremental=not args.full,
                event_types=args.event_type,
                max_logs=args.max_logs,
            )
        except ComplianceError as exc:
            log.error("수집 실패: %s", exc)
            return 1
        stats = store.stats()

    payload = {"result": result.to_dict(), "stats": stats}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(
            f"다운로드 {result.fetched}건 · 레코드 {result.records}건 · "
            f"신규 저장 {result.saved}건 · 누적 {stats['total']}건"
        )
    return 1 if result.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
