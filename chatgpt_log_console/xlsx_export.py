"""검색·수집 결과를 엑셀(.xlsx)로 만든다. openpyxl 만 쓴다.

큰 표를 다루므로 write_only 모드로 한 줄씩 흘려보낸다. 메모리에 표 전체를
올리지 않아야 수만 건도 견딘다. 기본 시트 외에 분석용 요약 시트를 함께 만든다.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from io import BytesIO

KST = timezone(timedelta(hours=9))

# (열 키, 머리글, 너비)
MESSAGE_COLUMNS = [
    ("ts_kst", "시간(한국)", 19),
    ("ts", "시간(UTC)", 19),
    ("event_type", "이벤트", 22),
    ("user", "사용자", 26),
    ("action", "역할·동작", 14),
    ("conversation_id", "대화 ID", 38),
    ("content", "내용", 100),
]
RAW_COLUMN = ("raw", "원본 JSON", 60)

_CELL_LIMIT = 32000        # 엑셀 한 칸 한계(32767)보다 넉넉히 줄인다
EXCEL_ROW_LIMIT = 1_000_000  # 엑셀 한계는 1,048,576 행. 여유를 둔다.


def _cell(value) -> str:
    if value is None:
        return ""
    text = value if isinstance(value, str) else str(value)
    # 엑셀은 제어문자를 거부한다. 줄바꿈·탭만 남기고 정리한다.
    text = "".join(ch for ch in text if ch in "\n\t" or ord(ch) >= 32)
    return text[:_CELL_LIMIT]


def to_kst(iso: str) -> str:
    """UTC ISO 문자열을 한국 시각으로. 분석할 때 UTC 로는 감이 안 온다."""
    if not iso:
        return ""
    try:
        moment = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return ""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(KST).strftime("%Y-%m-%d %H:%M:%S")


def _workbook():
    try:
        from openpyxl import Workbook
    except ImportError as exc:  # pragma: no cover - 패키지 미설치 안내
        raise RuntimeError(
            "엑셀 저장에는 openpyxl 이 필요합니다. 설치: pip install openpyxl"
        ) from exc
    return Workbook(write_only=True)


def _머리글(sheet, columns) -> None:
    from openpyxl.cell import WriteOnlyCell
    from openpyxl.styles import Alignment, Font

    for 번호, (_, _, 너비) in enumerate(columns, start=1):
        sheet.column_dimensions[_열이름(번호)].width = 너비
    줄 = []
    for _, 이름, _ in columns:
        칸 = WriteOnlyCell(sheet, value=이름)
        칸.font = Font(bold=True)
        칸.alignment = Alignment(vertical="center")
        줄.append(칸)
    sheet.append(줄)
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:{_열이름(len(columns))}1048576"


def _열이름(번호: int) -> str:
    이름 = ""
    while 번호:
        번호, 나머지 = divmod(번호 - 1, 26)
        이름 = chr(65 + 나머지) + 이름
    return 이름


def build_workbook_bytes(rows: list[dict], *, sheet_title: str = "logs",
                         with_raw: bool = True) -> bytes:
    """행 목록을 xlsx 바이트로. (기존 호출부 호환용 - 한 시트만 만든다)"""
    columns = MESSAGE_COLUMNS + ([RAW_COLUMN] if with_raw else [])
    workbook = _workbook()
    sheet = workbook.create_sheet(sheet_title[:31] or "logs")
    _머리글(sheet, columns)
    for row in rows:
        sheet.append([_cell(to_kst(row.get("ts")) if key == "ts_kst" else row.get(key))
                      for key, _, _ in columns])
    return _저장(workbook)


def build_analysis_workbook(rows: list[dict], *, with_raw: bool = False) -> bytes:
    """분석용 통합 문서.

      대화      메시지 한 줄씩 (원본 순서: 대화별 → 시간순)
      대화별    대화 하나당 한 줄 - 언제, 누가, 몇 마디, 첫 질문은 무엇이었나
      사용자별  사용자 한 명당 한 줄 - 메시지·대화 수, 처음/마지막 사용 시각
      일자별    날짜 한 줄씩 - 메시지·대화·사용자 수
    """
    columns = MESSAGE_COLUMNS + ([RAW_COLUMN] if with_raw else [])
    workbook = _workbook()

    본문 = workbook.create_sheet("대화")
    _머리글(본문, columns)

    대화별: dict[str, dict] = {}
    사용자별: dict[str, dict] = defaultdict(
        lambda: {"메시지": 0, "대화": set(), "처음": "", "마지막": ""})
    일자별: dict[str, dict] = defaultdict(lambda: {"메시지": 0, "대화": set(), "사용자": set()})

    for row in rows:
        시각 = row.get("ts") or ""
        한국시각 = to_kst(시각)
        본문.append([_cell(한국시각 if key == "ts_kst" else row.get(key))
                    for key, _, _ in columns])

        대화id = row.get("conversation_id") or ""
        사용자 = row.get("user") or ""
        내용 = row.get("content") or ""

        if 대화id:
            묶음 = 대화별.setdefault(대화id, {"시작": 한국시각, "끝": 한국시각, "사용자": set(),
                                          "메시지": 0, "첫질문": ""})
            묶음["메시지"] += 1
            묶음["끝"] = 한국시각 or 묶음["끝"]
            if 사용자:
                묶음["사용자"].add(사용자)
            if not 묶음["첫질문"] and (row.get("action") == "사용자" or "사용자:" in 내용):
                묶음["첫질문"] = 내용.replace("사용자:", "", 1).strip()[:200]

        if 사용자:
            사람 = 사용자별[사용자]
            사람["메시지"] += 1
            if 대화id:
                사람["대화"].add(대화id)
            if 한국시각:
                사람["처음"] = min(사람["처음"] or 한국시각, 한국시각)
                사람["마지막"] = max(사람["마지막"], 한국시각)

        날짜 = 한국시각[:10]
        if 날짜:
            하루 = 일자별[날짜]
            하루["메시지"] += 1
            if 대화id:
                하루["대화"].add(대화id)
            if 사용자:
                하루["사용자"].add(사용자)

    # ── 대화별 ──────────────────────────────────────────────────────
    시트 = workbook.create_sheet("대화별")
    _머리글(시트, [("a", "시작(한국)", 19), ("b", "끝(한국)", 19), ("c", "사용자", 26),
                 ("d", "메시지 수", 11), ("e", "첫 질문", 90), ("f", "대화 ID", 38)])
    for 대화id, 값 in sorted(대화별.items(), key=lambda 항목: 항목[1]["시작"], reverse=True):
        시트.append([값["시작"], 값["끝"], ", ".join(sorted(값["사용자"])),
                    값["메시지"], _cell(값["첫질문"]), 대화id])

    # ── 사용자별 ────────────────────────────────────────────────────
    시트 = workbook.create_sheet("사용자별")
    _머리글(시트, [("a", "사용자", 30), ("b", "메시지 수", 11), ("c", "대화 수", 10),
                 ("d", "처음 사용(한국)", 19), ("e", "마지막 사용(한국)", 19)])
    for 사용자, 값 in sorted(사용자별.items(), key=lambda 항목: 항목[1]["메시지"], reverse=True):
        시트.append([사용자, 값["메시지"], len(값["대화"]), 값["처음"], 값["마지막"]])

    # ── 일자별 ──────────────────────────────────────────────────────
    시트 = workbook.create_sheet("일자별")
    _머리글(시트, [("a", "날짜(한국)", 14), ("b", "메시지 수", 11),
                 ("c", "대화 수", 10), ("d", "사용자 수", 11)])
    for 날짜, 값 in sorted(일자별.items()):
        시트.append([날짜, 값["메시지"], len(값["대화"]), len(값["사용자"])])

    return _저장(workbook)


def _저장(workbook) -> bytes:
    buffer = BytesIO()
    workbook.save(buffer)
    workbook.close()
    return buffer.getvalue()


def write_csv(rows: list[dict], path, *, with_raw: bool = False) -> None:
    """엑셀이 버거울 만큼 클 때를 위한 CSV. 엑셀에서 바로 열리도록 BOM 을 붙인다."""
    import csv

    columns = MESSAGE_COLUMNS + ([RAW_COLUMN] if with_raw else [])
    with open(path, "w", encoding="utf-8-sig", newline="") as 파일:
        기록 = csv.writer(파일)
        기록.writerow([이름 for _, 이름, _ in columns])
        for row in rows:
            기록.writerow([to_kst(row.get("ts")) if key == "ts_kst" else (row.get(key) or "")
                          for key, _, _ in columns])
