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
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import keystore  # noqa: E402
from collector import collect  # noqa: E402
from compliance import ComplianceClient, ComplianceError  # noqa: E402
from records import PARSER_VERSION, normalize  # noqa: E402
from settings import DATA_DIR, DEFAULT_MAX_LOGS, RETENTION_DAYS, db_path  # noqa: E402
from store import LogStore  # noqa: E402
from xlsx_export import EXCEL_ROW_LIMIT, build_analysis_workbook, write_csv  # noqa: E402

log = logging.getLogger("export")
대화이벤트 = "CONVERSATION_MESSAGE"


class 진행표시:
    """같은 줄을 덮어써 진행 상황을 보여준다. 오래 걸려도 멈춘 게 아님을 알 수 있다."""

    def __init__(self, 간격: float = 1.0):
        self.시작 = time.monotonic()
        # 0.0 으로 두면 안 된다. monotonic() 은 부팅 후 경과 시간이라 값이 작을 때
        # '방금 찍었다' 로 오해해 첫 진행률이 안 나온다.
        self.마지막 = float("-inf")
        self.간격 = 간격

    @staticmethod
    def _시간(초: float) -> str:
        분, 초 = divmod(int(초), 60)
        시, 분 = divmod(분, 60)
        return f"{시}시간 {분}분" if 시 else (f"{분}분 {초}초" if 분 else f"{초}초")

    def __call__(self, 상태: dict) -> None:
        지금 = time.monotonic()
        if 지금 - self.마지막 < self.간격:
            return
        self.마지막 = 지금
        줄 = (f"  목록 {상태['listed']:,}건 · 다운로드 {상태['fetched']:,}건 · "
              f"저장 {상태['saved']:,}건 · {self._시간(지금 - self.시작)} 경과")
        print(f"\r{줄:<78}", end="", flush=True)

    def 끝(self) -> None:
        print(f"\r{' ' * 78}\r", end="", flush=True)


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
    parser.add_argument("--max-logs", type=int, default=DEFAULT_MAX_LOGS,
                        help=f"한 번에 내려받을 로그 수 상한 (기본 {DEFAULT_MAX_LOGS:,})")
    parser.add_argument("--out", help="저장할 폴더 (기본: 바탕화면)")
    parser.add_argument("--db", help="SQLite 파일 경로")
    parser.add_argument("--no-open", action="store_true", help="다 만든 뒤 열지 않는다")
    parser.add_argument("--csv", action="store_true",
                        help="엑셀 대신 CSV 로 저장 (아주 클 때. 엑셀에서 바로 열립니다)")
    parser.add_argument("--with-raw", action="store_true",
                        help="원본 JSON 열도 함께 넣는다 (파일이 크게 늘어납니다)")
    parser.add_argument("-q", "--quiet", action="store_true")
    args = parser.parse_args(argv)

    # 진행률을 한 줄로 덮어쓰며 보여주므로, 로그가 화면에 섞이면 읽기 어렵다.
    # 자세한 기록은 파일로 남기고 화면은 깨끗하게 둔다.
    handlers: list[logging.Handler] = []
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(DATA_DIR / "export.log", encoding="utf-8"))
    except OSError:  # pragma: no cover
        pass
    화면 = logging.StreamHandler(sys.stderr)
    화면.setLevel(logging.ERROR)          # 오류만 화면에
    handlers.append(화면)
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S")
    if args.quiet:
        logging.getLogger().setLevel(logging.WARNING)

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
            print(f"  최근 {args.days}일치를 받는 중입니다.")
            print(f"  처음 받을 때는 몇 분에서 수십 분까지 걸릴 수 있습니다"
                  f" (로그 최대 {args.max_logs:,}개).")
            print("  중간에 닫아도 그때까지 받은 것은 저장돼 있고, 다시 실행하면 이어서 받습니다.")
            print()
            표시 = 진행표시()
            try:
                결과 = collect(
                    ComplianceClient(key), store,
                    days=args.days,
                    event_types=None if args.all else [대화이벤트],
                    max_logs=args.max_logs,
                    progress=표시,
                )
            except ComplianceError as exc:
                표시.끝()
                print()
                print(f"  받아오지 못했습니다: {exc}")
                print()
                return 1
            except KeyboardInterrupt:
                표시.끝()
                print()
                print("  중단했습니다. 그때까지 받은 것은 저장돼 있습니다.")
                print("  다시 실행하면 이어서 받습니다.")
                print()
                return 130
            표시.끝()
            print(f"  다운로드 {결과.fetched:,}건 · 새로 저장 {결과.saved:,}건"
                  f" · 이미 있던 것 {max(결과.records - 결과.saved, 0):,}건")
            if 결과.truncated:
                print(f"  상한({args.max_logs:,}개)에 걸려 일부만 받았습니다."
                      f" 다시 실행하면 이어서 받습니다.")
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
    폴더 = Path(args.out or 기본_저장위치())
    폴더.mkdir(parents=True, exist_ok=True)
    때 = f"{datetime.now():%Y%m%d_%H%M}"

    # 엑셀 한 시트에 담을 수 있는 행 수에는 한계가 있다. 넘치면 나눠 저장한다.
    덩어리들 = [행들[i:i + EXCEL_ROW_LIMIT] for i in range(0, len(행들), EXCEL_ROW_LIMIT)] or [[]]
    만든파일: list[Path] = []
    for 번호, 덩어리 in enumerate(덩어리들, start=1):
        꼬리 = "" if len(덩어리들) == 1 else f"_{번호}"
        print(f"  엑셀 파일을 만드는 중입니다… ({len(덩어리):,}건){' ' * 20}", end="\r", flush=True)
        if args.csv:
            파일 = 폴더 / f"{이름}_{때}{꼬리}.csv"
            write_csv(덩어리, 파일, with_raw=args.with_raw)
        else:
            파일 = 폴더 / f"{이름}_{때}{꼬리}.xlsx"
            파일.write_bytes(build_analysis_workbook(덩어리, with_raw=args.with_raw))
        try:
            파일.chmod(0o600)          # 대화 내용이 담긴다
        except OSError:                # pragma: no cover
            pass
        만든파일.append(파일)
    print(" " * 60, end="\r")

    대화수 = len({행.get("conversation_id") for 행 in 행들 if 행.get("conversation_id")})
    사람수 = len({행.get("user") for 행 in 행들 if 행.get("user")})
    print()
    for 파일 in 만든파일:
        print(f"  저장했습니다: {파일}  ({파일.stat().st_size / 1024 / 1024:.1f} MB)")
    print(f"  메시지 {len(행들):,}건 · 대화 {대화수:,}개 · 사용자 {사람수}명")
    print(f"  (DB 누적 {통계['total']:,}건 · {통계['oldest'][:10]} ~ {통계['newest'][:10]})")
    if not args.csv:
        print()
        print("  시트 구성 - 대화 / 대화별 / 사용자별 / 일자별")
        print("  머리글에 필터가 걸려 있어 바로 정렬·집계하실 수 있습니다.")
    print()

    if not args.no_open and 만든파일:
        열기(만든파일[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
