"""검색·수집 결과를 엑셀(.xlsx)로 만든다. openpyxl 만 쓴다."""

from __future__ import annotations

from io import BytesIO

HEADERS = [
    ("ts", "시간(UTC)"),
    ("event_type", "이벤트"),
    ("user", "사용자"),
    ("action", "동작"),
    ("conversation_id", "대화 ID"),
    ("summary", "내용 요약"),
    ("content", "내용 전체"),
    ("id", "로그 ID"),
    ("raw", "원본 JSON"),
]
_CELL_LIMIT = 32000  # 엑셀 한 칸 한계(32767)보다 넉넉히 줄여 자른다
_WIDTHS = [20, 20, 28, 24, 30, 60, 80, 32, 60]


def build_workbook_bytes(rows: list[dict], *, sheet_title: str = "logs") -> bytes:
    """행 목록을 xlsx 바이트로 만든다."""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font
    except ImportError as exc:  # pragma: no cover - 패키지 미설치 안내
        raise RuntimeError(
            "엑셀 저장에는 openpyxl 이 필요합니다. 설치: pip install openpyxl"
        ) from exc

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = sheet_title[:31] or "logs"

    sheet.append([label for _, label in HEADERS])
    for cell in sheet[1]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(vertical="center")
    sheet.freeze_panes = "A2"

    for row in rows:
        sheet.append([_cell(row.get(key)) for key, _ in HEADERS])

    for index, width in enumerate(_WIDTHS, start=1):
        sheet.column_dimensions[sheet.cell(row=1, column=index).column_letter].width = width

    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _cell(value) -> str:
    if value is None:
        return ""
    text = value if isinstance(value, str) else str(value)
    # 엑셀은 제어문자를 거부한다. 줄바꿈만 남기고 정리한다.
    text = "".join(ch for ch in text if ch == "\n" or ch == "\t" or ord(ch) >= 32)
    return text[:_CELL_LIMIT]
