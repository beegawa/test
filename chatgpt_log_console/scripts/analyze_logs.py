#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ChatGPT 사용 로그 분석기 (표준 라이브러리만 사용)

대화내용_받기.BAT 가 내려받은 로그 파일(SQLite / JSON / JSONL / CSV / ZIP)을
자동으로 찾아 읽고, 월간 사용 현황 HTML 리포트를 만든다.

사용법:
    python analyze_logs.py --base <폴더> [--period YYYY-MM] [--out reports]
    python analyze_logs.py --input a.sqlite b.jsonl --period 2026-09
"""

from __future__ import annotations

import argparse
import calendar
import csv
import io
import json
import os
import re
import sqlite3
import sys
import tempfile
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))

DATA_EXTS = {".sqlite", ".sqlite3", ".db", ".db3", ".jsonl", ".ndjson", ".json", ".csv", ".zip"}
SKIP_DIRS = {"reports", "logs", "scripts", ".state", ".git", "__pycache__", ".venv", "venv"}

# ---------------------------------------------------------------- 로그 적재


def log(msg: str) -> None:
    print(f"[analyze] {msg}", flush=True)


def find_data_files(base: str) -> list[str]:
    """base 폴더에서 로그 데이터로 보이는 파일을 최신순으로 찾는다."""
    found = []
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for name in files:
            ext = os.path.splitext(name)[1].lower()
            if ext not in DATA_EXTS:
                continue
            path = os.path.join(root, name)
            try:
                if os.path.getsize(path) < 128:
                    continue
            except OSError:
                continue
            if os.path.basename(path) in ("settings.json", "state.json", "package.json"):
                continue
            found.append(path)
    found.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return found


def _looks_like_sqlite(path: str) -> bool:
    try:
        with open(path, "rb") as fh:
            return fh.read(16).startswith(b"SQLite format 3")
    except OSError:
        return False


def load_records(paths: list[str]) -> list[dict]:
    """여러 파일에서 레코드(dict)를 모두 읽어 하나의 리스트로 돌려준다."""
    records: list[dict] = []
    for path in paths:
        try:
            part = load_one(path)
        except Exception as exc:  # 한 파일이 깨져도 나머지는 계속 읽는다
            log(f"건너뜀 ({os.path.basename(path)}): {exc}")
            continue
        if part:
            log(f"{os.path.basename(path)} → {len(part):,}건")
            records.extend(part)
    return records


def load_one(path: str) -> list[dict]:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".zip":
        return load_zip(path)
    if _looks_like_sqlite(path):
        return load_sqlite(path)
    if ext in (".jsonl", ".ndjson"):
        return load_jsonl(path)
    if ext == ".json":
        return load_json(path)
    if ext == ".csv":
        return load_csv(path)
    return []


def load_zip(path: str) -> list[dict]:
    out: list[dict] = []
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(path) as zf:
            for info in zf.infolist():
                if info.is_dir() or info.file_size < 128:
                    continue
                if os.path.splitext(info.filename)[1].lower() not in DATA_EXTS - {".zip"}:
                    continue
                target = zf.extract(info, tmp)
                try:
                    out.extend(load_one(target))
                except Exception as exc:
                    log(f"zip 내부 건너뜀 ({info.filename}): {exc}")
    return out


def load_sqlite(path: str) -> list[dict]:
    uri = "file:" + path.replace("?", "%3f").replace("#", "%23") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    out: list[dict] = []
    try:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        for table in tables:
            if table.lower() in ("meta", "metadata", "schema_version", "cursor", "state"):
                continue
            try:
                rows = conn.execute(f'SELECT * FROM "{table}"')
            except sqlite3.Error:
                continue
            for row in rows:
                item = {k: row[k] for k in row.keys()}
                raw = item.get("raw") or item.get("payload") or item.get("data") or item.get("body")
                if isinstance(raw, (bytes, bytearray)):
                    raw = raw.decode("utf-8", "replace")
                if isinstance(raw, str) and raw.strip()[:1] in ("{", "["):
                    try:
                        parsed = json.loads(raw)
                        if isinstance(parsed, dict):
                            merged = dict(item)
                            merged.pop("raw", None)
                            merged["_row"] = {k: v for k, v in item.items() if k != "raw"}
                            merged.update(parsed)
                            item = merged
                    except (ValueError, TypeError):
                        pass
                out.append(item)
    finally:
        conn.close()
    return out


def _iter_json_container(obj) -> list[dict]:
    if isinstance(obj, list):
        return [o for o in obj if isinstance(o, dict)]
    if isinstance(obj, dict):
        for key in ("data", "items", "logs", "results", "records", "events", "rows"):
            val = obj.get(key)
            if isinstance(val, list):
                return [o for o in val if isinstance(o, dict)]
        return [obj]
    return []


def load_json(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
        text = fh.read()
    stripped = text.lstrip()
    if stripped[:1] not in ("{", "["):
        return []
    try:
        return _iter_json_container(json.loads(text))
    except ValueError:
        return load_jsonl(path)  # 줄단위 JSON 이 .json 확장자로 온 경우


def load_jsonl(path: str) -> list[dict]:
    out: list[dict] = []
    with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
        for line in fh:
            line = line.strip().rstrip(",")
            if not line or line in ("[", "]"):
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            out.extend(_iter_json_container(obj))
    return out


def load_csv(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8-sig", errors="replace", newline="") as fh:
        sample = fh.read(8192)
        fh.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        return [dict(row) for row in csv.DictReader(fh, dialect=dialect)]


# ---------------------------------------------------------------- 정규화

def dig(obj, *path, default=None):
    """중첩 dict 를 안전하게 파고든다. dig(r, 'message', 'author', 'type')"""
    cur = obj
    for key in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
        if cur is None:
            return default
    return cur


def first(*vals, default=None):
    for v in vals:
        if v not in (None, "", []):
            return v
    return default


def parse_ts(value) -> datetime | None:
    """ISO8601 / epoch(초·밀리초) 문자열·숫자를 UTC datetime 으로."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)) or (isinstance(value, str) and re.fullmatch(r"\d{9,14}(\.\d+)?", value.strip())):
        num = float(value)
        if num > 1e11:      # 밀리초
            num /= 1000.0
        try:
            return datetime.fromtimestamp(num, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str):
        return None
    text = value.strip().replace("Z", "+00:00")
    text = re.sub(r"(\.\d{6})\d+", r"\1", text)          # 나노초 절삭
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(text[:19], fmt)
                break
            except ValueError:
                continue
        else:
            return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def extract_text(content) -> str:
    """message.content 가 문자열·dict·parts 배열 어느 형태여도 본문만 뽑는다."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(extract_text(c) for c in content if c is not None)
    if isinstance(content, dict):
        ctype = content.get("type") or content.get("content_type")
        if ctype in ("image", "image_asset_pointer", "file", "audio"):
            return ""
        for key in ("value", "text", "body"):
            if isinstance(content.get(key), str):
                return content[key]
        parts = content.get("parts") or content.get("content")
        if parts is not None and parts is not content:
            return extract_text(parts)
    return ""


def normalize(raw: dict) -> dict | None:
    """원본 레코드 한 건을 공통 스키마로 변환한다."""
    row = raw.get("_row") or {}
    event = str(first(raw.get("event_type"), raw.get("eventType"), raw.get("type"),
                      row.get("event_type"), default="")).upper()
    msg = raw.get("message") if isinstance(raw.get("message"), dict) else {}
    author = msg.get("author") if isinstance(msg.get("author"), dict) else {}
    conv = raw.get("conversation") if isinstance(raw.get("conversation"), dict) else {}
    actor = raw.get("actor") if isinstance(raw.get("actor"), dict) else {}

    ts = parse_ts(first(raw.get("timestamp"), raw.get("ts"), raw.get("created_at"),
                        raw.get("createdAt"), msg.get("create_time"), row.get("ts"),
                        row.get("timestamp"), raw.get("time"), raw.get("date")))
    if ts is None:
        return None

    user = first(dig(actor, "user_email"), dig(actor, "email"), raw.get("user_email"),
                 raw.get("user"), row.get("user"), dig(actor, "user", "email"),
                 raw.get("email"), default="(unknown)")
    user = str(user).strip().lower()

    is_auth = "AUTH" in event or isinstance(raw.get("action_data"), dict)
    if is_auth:
        meta = raw.get("request_metadata") if isinstance(raw.get("request_metadata"), dict) else {}
        action = str(first(dig(raw, "action_data", "action"), raw.get("action"), default="")).lower()
        return {
            "kind": "auth",
            "ts": ts,
            "user": user,
            "action": action,
            "role": str(first(dig(raw, "action_data", "role"), raw.get("role"), default="")).lower(),
            "ua": str(first(meta.get("client_user_agent"), raw.get("user_agent"), default="")),
            "country": str(first(dig(meta, "client_ip_details", "country"), default="")),
            "city": str(first(dig(meta, "client_ip_details", "city"), default="")),
            "failed": ("fail" in action or "denied" in action or "error" in action
                       or str(raw.get("success", "")).lower() == "false"),
        }

    text = extract_text(first(msg.get("content"), raw.get("content"), row.get("content"), default=""))
    role = str(first(author.get("type"), author.get("role"), raw.get("role"), default="user")).lower()
    tools = msg.get("tools_used") or author.get("tools_used") or raw.get("tools_used") or []
    if isinstance(tools, str):
        tools = [t.strip() for t in re.split(r"[,\s]+", tools) if t.strip()]
    skills = author.get("skills_used_names") or msg.get("skills_used_names") or []
    if isinstance(skills, str):
        skills = [s.strip() for s in re.split(r"[,\s]+", skills) if s.strip()]
    files = msg.get("files") or raw.get("files") or []
    exts = []
    if isinstance(files, list):
        for f in files:
            name = f.get("name") if isinstance(f, dict) else (f if isinstance(f, str) else "")
            ext = os.path.splitext(str(name))[1].lower().lstrip(".")
            exts.append(ext or "기타")

    return {
        "kind": "message",
        "ts": ts,
        "user": user,
        "role": "assistant" if role in ("assistant", "system", "tool") else "user",
        "text": text or "",
        "conv_id": str(first(conv.get("id"), raw.get("conversation_id"), row.get("conversation_id"),
                             default=f"noconv:{user}:{ts:%Y%m%d}")),
        "conv_title": str(first(conv.get("title"), raw.get("title"), default="")),
        "gpt_name": str(first(conv.get("gpt_name"), raw.get("gpt_name"), default="")),
        "project": str(first(conv.get("project_name"), raw.get("project_name"), default="")),
        "mode": str(first(conv.get("mode"), default="")),
        "temporary": bool(conv.get("is_temporary_chat")),
        "model": str(first(author.get("model"), msg.get("model"), raw.get("model"), default="")),
        "client": str(first(author.get("client_type"), raw.get("client_type"), default="")),
        "tools": [str(t) for t in tools if t],
        "skills": [str(s) for s in skills if s],
        "file_exts": exts,
    }


# ---------------------------------------------------------------- 마스킹

RE_PHONE = re.compile(r"\b01[016789][-. ]?\d{3,4}[-. ]?\d{4}\b|\b0\d{1,2}[-. ]\d{3,4}[-. ]\d{4}\b")
RE_EMAIL = re.compile(r"\b[\w.+-]{1,40}@[\w-]{1,30}(?:\.[\w-]{2,12}){1,3}\b")
RE_RRN = re.compile(r"\b\d{6}[-\s]?[1-4]\d{6}\b")
RE_CARD = re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b")
RE_SECRET = re.compile(r"(비밀번호|패스워드|password|passwd|api[_\s-]?key|secret[_\s-]?key|token)\s*[:=]\s*\S+", re.I)


def mask(text: str) -> str:
    """개인정보 패턴을 가린다. (긴 본문은 먼저 잘라서 정규식 백트래킹을 피한다)"""
    text = (text or "")[:400]
    text = RE_RRN.sub("******-*******", text)
    text = RE_CARD.sub("****-****-****-****", text)
    text = RE_PHONE.sub("010-****-****", text)
    text = RE_EMAIL.sub(lambda m: m.group(0).split("@")[0][:2] + "***@" + m.group(0).split("@")[-1], text)
    text = RE_SECRET.sub(lambda m: m.group(0).split(":")[0].split("=")[0] + ": ****", text)
    return text


# ---------------------------------------------------------------- 카테고리 분류

CATEGORIES = [
    ("translate", "번역·외국어", ["번역", "영작", "translate", "영어로", "중국어", "일본어", "베트남어",
                                  "스페인어", "영문으로", "한국어로", "의역", "원어민", "어순", "문법",
                                  "english", "chinese", "japanese"]),
    ("writing", "이메일·문장 작성·윤문", ["메일", "이메일", "email", "회신", "답장", "정중하게", "문구",
                                          "윤문", "다듬어", "매끄럽게", "공지문", "인사말", "제목 추천",
                                          "카피", "문장으로", "표현으로", "어투"]),
    ("docs", "문서·보고서·요약", ["보고서", "요약", "정리해", "기획안", "제안서", "회의록", "발표",
                                  "ppt", "슬라이드", "목차", "품의", "결재", "양식", "초안", "개조식",
                                  "summary", "문서화"]),
    ("data", "엑셀·데이터·계산", ["엑셀", "excel", "수식", "vlookup", "xlookup", "피벗", "함수",
                                  "매크로", "vba", "csv", "시트", "계산", "합계", "평균", "그래프",
                                  "차트", "통계", "데이터 정리"]),
    ("research", "리서치·시장·바이어 조사", ["시장", "트렌드", "경쟁사", "바이어", "브랜드 조사", "동향",
                                            "리서치", "조사해", "찾아줘", "알려줘 최신", "전망", "사례",
                                            "벤치마킹", "고객사", "업체 정보"]),
    ("production", "생산·품질·소재", ["원단", "소재", "봉제", "패턴", "샘플", "불량", "품질", "검사",
                                      "염색", "가공", "사이즈 스펙", "작업지시", "공장", "생산", "납기",
                                      "테스트 리포트", "컬러웨이"]),
    ("cost", "원가·가격·협상", ["원가", "단가", "견적", "가격", "마진", "네고", "협상", "코스트",
                                "인상", "인하", "정산", "환율", "cost", "quotation"]),
    ("trade", "무역·물류·통관", ["수출", "수입", "통관", "관세", "hs코드", "선적", "b/l", "bl",
                                 "인보이스", "invoice", "패킹리스트", "l/c", "신용장", "fta",
                                 "원산지", "포워더", "컨테이너", "물류", "운임", "물류비"]),
    ("admin", "경영지원(회계·세무·법무·HR)", ["회계", "세금", "세무", "부가세", "전표", "계약서",
                                             "법무", "규정", "취업규칙", "연차", "급여", "인사",
                                             "채용", "노무", "보험", "감사", "내부통제", "근로기준법"]),
    ("it", "IT·ERP·RPA·AI활용", ["erp", "rpa", "시스템", "sql", "쿼리", "파이썬", "python", "코드",
                                 "스크립트", "오류", "에러", "api", "프로그램", "설치", "서버", "chatgpt",
                                 "gpt 활용", "프롬프트", "자동화", "엑셀 매크로 코드"]),
    ("design", "이미지·영상·디자인", ["이미지", "사진", "그려", "디자인", "로고", "배경", "썸네일",
                                      "영상", "편집", "일러스트", "도식", "목업", "그림"]),
    ("personal", "일반 질의·개인 생활", ["주식", "코인", "부동산", "여행", "맛집", "레시피", "요리",
                                        "건강", "병원", "약", "운동", "다이어트", "영화", "드라마",
                                        "게임", "연애", "결혼", "육아", "자녀", "학교 숙제", "취미",
                                        "로또", "운세", "생일", "선물 추천", "날씨"]),
]
AUTO_CODE = "auto"
AUTO_LABEL = "예약·반복 자동작업"
ETC_CODE = "etc"
ETC_LABEL = "기타·분류 불가"
CATEGORY_LABELS = {code: label for code, label, _ in CATEGORIES}
CATEGORY_LABELS[AUTO_CODE] = AUTO_LABEL
CATEGORY_LABELS[ETC_CODE] = ETC_LABEL
CATEGORY_ORDER = [c for c, _, _ in CATEGORIES] + [AUTO_CODE, ETC_CODE]


def classify(text: str, title: str = "") -> str:
    """키워드 규칙 기반 대화 분류. (LLM 분류보다 정확도가 낮다 - 리포트에 단서 표기)"""
    blob = (title + "\n" + text).lower()[:1500]
    scores: dict[str, int] = {}
    for code, _label, keywords in CATEGORIES:
        hit = sum(1 for kw in keywords if kw in blob)
        if hit:
            scores[code] = hit
    if not scores:
        return ETC_CODE
    # 작업 유형(번역·윤문)이 걸리면 업무 도메인보다 우선한다
    for code in ("translate", "writing"):
        if scores.get(code, 0) >= 2:
            return code
    best = max(scores.values())
    for code in CATEGORY_ORDER:          # 동점이면 정의 순서가 이긴다
        if scores.get(code) == best:
            return code
    return ETC_CODE


# ---------------------------------------------------------------- 집계

WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]
SCRIPT_UA = ("aiohttp", "openid-client", "python-requests", "curl", "okhttp", "httpx", "postman")


def kst(dt: datetime) -> datetime:
    return dt.astimezone(KST)


def month_bounds(period: str) -> tuple[datetime, datetime]:
    year, month = int(period[:4]), int(period[5:7])
    start = datetime(year, month, 1, tzinfo=KST)
    last = calendar.monthrange(year, month)[1]
    end = datetime(year, month, last, 23, 59, 59, tzinfo=KST)
    return start, end


def prev_period(period: str) -> str:
    year, month = int(period[:4]), int(period[5:7])
    return f"{year - 1}-12" if month == 1 else f"{year}-{month - 1:02d}"


def norm_prompt(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())[:120]


def dedupe(rows: list[dict]) -> list[dict]:
    seen: set[tuple] = set()
    out = []
    for r in rows:
        key = (r["kind"], r["ts"].isoformat(), r["user"], r.get("conv_id", ""),
               hash(r.get("text", "")[:200]), r.get("action", ""))
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def top_n(counter: Counter, n: int) -> list[dict]:
    return [{"name": k, "value": v} for k, v in counter.most_common(n)]


def build_model(records: list[dict], period: str) -> dict:
    rows = [n for n in (normalize(r) for r in records) if n]
    rows = dedupe(rows)
    msgs = [r for r in rows if r["kind"] == "message"]
    auths = [r for r in rows if r["kind"] == "auth"]

    all_ts = [kst(r["ts"]) for r in rows]
    start, end = month_bounds(period)

    # ---- 자동작업(같은 사용자가 같은 프롬프트를 10회 이상) 판정: 전체 기간 기준
    repeat = Counter()
    repeat_days = defaultdict(set)
    for r in msgs:
        if r["role"] != "user":
            continue
        key = (r["user"], norm_prompt(r["text"]))
        if len(key[1]) < 15:
            continue
        repeat[key] += 1
        repeat_days[key].add(kst(r["ts"]).date())
    # 예약·자동작업: 같은 사람이 같은 프롬프트를 10회 이상, 서로 다른 5일 이상에 걸쳐 보낸 경우
    auto_keys = {k for k, c in repeat.items() if c >= 10 and len(repeat_days[k]) >= 5}

    # ---- 월별 추이 (최근 6개월)
    monthly = Counter()
    monthly_users = defaultdict(set)
    for r in msgs:
        if r["role"] != "user" or not r["text"].strip():
            continue
        key = f"{kst(r['ts']):%Y-%m}"
        monthly[key] += 1
        monthly_users[key].add(r["user"])
    months = sorted(monthly)[-6:]
    trend = [{"name": m, "value": monthly[m], "users": len(monthly_users[m])} for m in months]

    cur = [r for r in msgs if start <= kst(r["ts"]) <= end]
    queries = [r for r in cur if r["role"] == "user" and r["text"].strip()]
    for q in queries:
        q["_auto"] = (q["user"], norm_prompt(q["text"])) in auto_keys
    human = [q for q in queries if not q["_auto"]]
    auto_q = [q for q in queries if q["_auto"]]

    # ---- 대화 단위 분류 → 질의에 전파
    convs: dict[str, dict] = {}
    for q in sorted(human, key=lambda r: r["ts"]):
        c = convs.setdefault(q["conv_id"], {"title": q["conv_title"], "texts": [], "users": set()})
        if len(c["texts"]) < 3:
            c["texts"].append(q["text"][:170])
        c["users"].add(q["user"])
    for cid, c in convs.items():
        c["code"] = classify("\n".join(c["texts"]), c["title"])
    for q in human:
        q["_cat"] = convs.get(q["conv_id"], {}).get("code", ETC_CODE)
    for q in auto_q:
        q["_cat"] = AUTO_CODE

    users = Counter(q["user"] for q in human)
    cat_q = Counter(q["_cat"] for q in queries)
    cat_c = Counter(c["code"] for c in convs.values())
    cat_rows = []
    total_q = sum(cat_q.values()) or 1
    for code in CATEGORY_ORDER:
        if not cat_q.get(code):
            continue
        cat_rows.append({
            "code": code, "name": CATEGORY_LABELS[code], "value": cat_q[code],
            "convs": cat_c.get(code, 0), "share": round(cat_q[code] * 100.0 / total_q, 1),
        })
    cat_rows.sort(key=lambda r: -r["value"])

    # ---- 일별 / 요일×시간 / 시간대
    daily = Counter()
    daily_users = defaultdict(set)
    for q in human:
        d = f"{kst(q['ts']):%Y-%m-%d}"
        daily[d] += 1
        daily_users[d].add(q["user"])
    day_list = []
    cursor = start
    while cursor <= end and cursor <= datetime.now(KST) + timedelta(days=1):
        key = f"{cursor:%Y-%m-%d}"
        day_list.append({"name": key, "value": daily.get(key, 0), "users": len(daily_users.get(key, ()))})
        cursor += timedelta(days=1)

    heat = [[0] * 24 for _ in range(7)]
    hours = [0] * 24
    for q in human:
        t = kst(q["ts"])
        heat[t.weekday()][t.hour] += 1
        hours[t.hour] += 1

    # ---- 상위 사용자 × 카테고리
    top_users = users.most_common(15)
    user_cat = defaultdict(Counter)
    for q in human:
        user_cat[q["user"]][q["_cat"]] += 1
    top_cat_codes = [r["code"] for r in cat_rows[:8]]
    matrix = [{"user": anon(u, i), "cells": [user_cat[u].get(c, 0) for c in top_cat_codes], "total": n}
              for i, (u, n) in enumerate(top_users[:10])]

    # ---- 모델·도구·채택률
    models = Counter(r["model"] for r in cur if r["role"] == "assistant" and r["model"])
    if not models:
        models = Counter(r["model"] for r in cur if r["model"])
    tools = Counter(t for r in cur for t in r["tools"])
    skills = Counter(s for r in cur for s in r["skills"])
    gpts = Counter(r["gpt_name"] for r in cur if r["gpt_name"])
    projects = Counter(r["project"] for r in cur if r["project"])
    exts = Counter(e for r in cur for e in r["file_exts"])
    clients = Counter(r["client"] for r in cur if r["client"])

    # ---- 보안 점검 (건수·인원만, 원문 비노출)
    def scan(pattern) -> tuple[int, int]:
        hits, who = 0, set()
        for q in queries:
            if pattern.search(q["text"][:500]):
                hits += 1
                who.add(q["user"])
        return hits, len(who)

    cur_auth = [a for a in auths if start <= kst(a["ts"]) <= end]
    domains = Counter(u.split("@")[-1] for u in users if "@" in u)
    main_domain = domains.most_common(1)[0][0] if domains else ""
    ext_admin = sorted({a["user"] for a in cur_auth
                        if ("admin" in a["role"] or "owner" in a["role"])
                        and main_domain and not a["user"].endswith("@" + main_domain)})
    script_login = sorted({a["user"] for a in cur_auth if any(s in a["ua"].lower() for s in SCRIPT_UA)})
    failed = sum(1 for a in cur_auth if a["failed"])
    countries = Counter(a["country"] for a in cur_auth if a["country"])

    phone_hit, rrn_hit, card_hit, secret_hit = scan(RE_PHONE), scan(RE_RRN), scan(RE_CARD), scan(RE_SECRET)
    security = [
        {"item": "전화번호 패턴 포함 질의", "hits": phone_hit[0], "people": phone_hit[1], "level": "warn"},
        {"item": "주민등록번호 패턴 포함 질의", "hits": rrn_hit[0], "people": rrn_hit[1], "level": "critical"},
        {"item": "카드번호 패턴 포함 질의", "hits": card_hit[0], "people": card_hit[1], "level": "critical"},
        {"item": "비밀번호·API 키 패턴 포함 질의", "hits": secret_hit[0], "people": secret_hit[1], "level": "serious"},
        {"item": "외부 도메인 계정의 관리자 권한 로그인", "hits": len(ext_admin), "people": len(ext_admin), "level": "serious"},
        {"item": "스크립트(자동화 도구) 로그인", "hits": len(script_login), "people": len(script_login), "level": "warn"},
        {"item": "로그인 실패·거부", "hits": failed, "people": 0, "level": "warn"},
    ]

    # ---- 개인 목적 사용 진단
    personal = [q for q in human if q["_cat"] == "personal"]
    per_user_personal = Counter(q["user"] for q in personal)
    heavy = [(u, n) for u, n in users.items() if n >= 20]
    over50 = sum(1 for u, n in heavy if per_user_personal.get(u, 0) / n >= 0.5)
    over30 = sum(1 for u, n in heavy if per_user_personal.get(u, 0) / n >= 0.3)
    top5_personal = sum(n for _, n in per_user_personal.most_common(5))
    worktime = sum(1 for q in personal if kst(q["ts"]).weekday() < 5 and 9 <= kst(q["ts"]).hour < 18)
    personal_stat = {
        "count": len(personal),
        "share": round(len(personal) * 100.0 / (len(human) or 1), 1),
        "users": len(per_user_personal),
        "heavy_users": len(heavy),
        "over50": over50,
        "over30": over30,
        "top5_share": round(top5_personal * 100.0 / (len(personal) or 1), 1),
        "worktime_share": round(worktime * 100.0 / (len(personal) or 1), 1),
    }

    # ---- 상위 사용자 실제 질의어 샘플 (마스킹·개인 카테고리 제외)
    samples = []
    for i, (u, n) in enumerate(top_users[:10]):
        pool = [q for q in human if q["user"] == u and q["_cat"] != "personal" and len(q["text"].strip()) >= 12]
        pool.sort(key=lambda r: r["ts"])
        picked, seen = [], set()
        stepper = max(1, len(pool) // 12)
        for q in pool[::stepper]:
            key = norm_prompt(q["text"])[:40]
            if key in seen:
                continue
            seen.add(key)
            picked.append({"ts": f"{kst(q['ts']):%m-%d %H:%M}",
                           "cat": CATEGORY_LABELS.get(q["_cat"], ETC_LABEL),
                           "text": mask(q["text"])[:220]})
            if len(picked) >= 10:
                break
        samples.append({"user": anon(u, i), "total": n, "items": picked})

    # ---- 전월 대비
    p_prev = prev_period(period)
    ps, pe = month_bounds(p_prev)
    prev_q = [r for r in msgs if r["role"] == "user" and r["text"].strip() and ps <= kst(r["ts"]) <= pe
              and (r["user"], norm_prompt(r["text"])) not in auto_keys]
    prev_stat = {"queries": len(prev_q), "users": len({r["user"] for r in prev_q}),
                 "convs": len({r["conv_id"] for r in prev_q})}

    conv_len = Counter()
    for q in human:
        conv_len[q["conv_id"]] += 1
    lens = sorted(conv_len.values())
    median = lens[len(lens) // 2] if lens else 0
    top10_share = round(sum(n for _, n in users.most_common(10)) * 100.0 / (len(human) or 1), 1)
    top20_share = round(sum(n for _, n in users.most_common(20)) * 100.0 / (len(human) or 1), 1)

    return {
        "period": period,
        "period_label": f"{period[:4]}년 {int(period[5:7])}월",
        "generated": f"{datetime.now(KST):%Y-%m-%d %H:%M}",
        "coverage": {
            "first": f"{min(all_ts):%Y-%m-%d}" if all_ts else "-",
            "last": f"{max(all_ts):%Y-%m-%d}" if all_ts else "-",
            "records": len(rows),
        },
        "kpi": {
            "users": len(users), "convs": len(convs), "queries": len(human),
            "auto": len(auto_q), "per_user": round(len(human) / (len(users) or 1), 1),
            "median_conv": median, "top10_share": top10_share, "top20_share": top20_share,
        },
        "prev": prev_stat,
        "trend": trend,
        "daily": day_list,
        "heat": heat,
        "hours": hours,
        "categories": cat_rows,
        "top_cat_names": [CATEGORY_LABELS[c] for c in top_cat_codes],
        "top_cat_short": [CATEGORY_LABELS[c].split("(")[0].split("·")[0][:6] for c in top_cat_codes],
        "top_users": [{"name": anon(u, i), "value": n} for i, (u, n) in enumerate(top_users)],
        "matrix": matrix,
        "models": top_n(models, 8),
        "tools": top_n(tools, 8),
        "skills": top_n(skills, 8),
        "gpts": top_n(gpts, 8),
        "projects": top_n(projects, 8),
        "exts": top_n(exts, 8),
        "clients": top_n(clients, 6),
        "security": security,
        "personal": personal_stat,
        "samples": samples,
        "countries": top_n(countries, 6),
        "auth_count": len(cur_auth),
    }


def anon(email: str, idx: int) -> str:
    """상위 사용자 표기: 아이디 앞 2글자만 남긴다."""
    local = email.split("@")[0]
    shown = local[:2] + "*" * max(1, len(local) - 2)
    return f"{shown} ({idx + 1})"


# ---------------------------------------------------------------- 요약 문장

def delta_text(now: int, before: int) -> str:
    if not before:
        return "전월 데이터 없음"
    diff = now - before
    pct = round(diff * 100.0 / before, 1)
    sign = "▲" if diff > 0 else ("▼" if diff < 0 else "–")
    return f"{sign} 전월 대비 {abs(pct)}% ({before:,} → {now:,})"


def summary_lines(m: dict) -> list[str]:
    k, p, pe = m["kpi"], m["prev"], m["personal"]
    lines = [
        f"{m['period_label']} 활성 사용자 {k['users']:,}명이 대화 {k['convs']:,}건·질의 {k['queries']:,}건을 사용했다. "
        f"({delta_text(k['queries'], p['queries'])})",
        f"상위 10명이 전체 질의의 {k['top10_share']}%, 상위 20명이 {k['top20_share']}%를 차지한다. "
        f"1인당 평균 {k['per_user']}건, 대화당 질의 중간값 {k['median_conv']}건.",
    ]
    if m["categories"]:
        top3 = ", ".join(f"{c['name']} {c['share']}%" for c in m["categories"][:3])
        lines.append(f"용도는 {top3} 순으로 많다.")
    lines.append(
        f"개인 목적으로 보이는 질의는 {pe['count']:,}건({pe['share']}%)이고, "
        f"20건 이상 사용자 {pe['heavy_users']}명 중 개인 비중 50% 이상은 {pe['over50']}명, 30% 이상은 {pe['over30']}명이다. "
        f"개인 질의의 {pe['top5_share']}%가 상위 5명에게서 나와 "
        + ("소수 집중 양상이다." if pe["top5_share"] >= 50 else "특정 인원에 쏠려 있지는 않다."))
    risky = [s for s in m["security"] if s["hits"] > 0 and s["level"] in ("critical", "serious")]
    lines.append("보안 점검에서 주의 항목 " + (", ".join(f"{s['item']} {s['hits']}건" for s in risky)
                                              if risky else "해당 없음(민감정보 패턴 미검출)") + ".")
    if k["auto"]:
        lines.append(f"동일 프롬프트 10회 이상 반복된 예약·자동작업 {k['auto']:,}건은 사용자 통계에서 분리했다.")
    return lines


# ---------------------------------------------------------------- HTML 리포트

HTML = r"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  :root{
    color-scheme: light;
    --surface-1:#fcfcfb; --surface-2:#f4f4f1; --border:#e2e1dc;
    --text-primary:#0b0b0b; --text-secondary:#52514e; --text-muted:#78766f;
    --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a; --s4:#eda100;
    --s5:#e87ba4; --s6:#008300; --s7:#4a3aa7; --s8:#e34948;
    --seq-0:#eef3fa; --seq-1:#cfe0f4; --seq-2:#9cc1e9; --seq-3:#5b95d9; --seq-4:#2a78d6; --seq-5:#17497f;
    --good:#008300; --warn:#eda100; --serious:#eb6834; --critical:#e34948;
    --grid:#e8e7e2;
  }
  @media (prefers-color-scheme: dark){
    :root:not([data-theme="light"]){
      color-scheme: dark;
      --surface-1:#1a1a19; --surface-2:#232321; --border:#35342f;
      --text-primary:#ffffff; --text-secondary:#c3c2b7; --text-muted:#93918a;
      --s1:#3987e5; --s2:#d95926; --s3:#199e70; --s4:#c98500;
      --s5:#d55181; --s6:#008300; --s7:#9085e9; --s8:#e66767;
      --seq-0:#1f2630; --seq-1:#23384f; --seq-2:#2b5480; --seq-3:#3672ad; --seq-4:#4a90dd; --seq-5:#77b2ef;
      --grid:#2e2e2a;
    }
  }
  :root[data-theme="dark"]{
    color-scheme: dark;
    --surface-1:#1a1a19; --surface-2:#232321; --border:#35342f;
    --text-primary:#ffffff; --text-secondary:#c3c2b7; --text-muted:#93918a;
    --s1:#3987e5; --s2:#d95926; --s3:#199e70; --s4:#c98500;
    --s5:#d55181; --s6:#008300; --s7:#9085e9; --s8:#e66767;
    --seq-0:#1f2630; --seq-1:#23384f; --seq-2:#2b5480; --seq-3:#3672ad; --seq-4:#4a90dd; --seq-5:#77b2ef;
    --grid:#2e2e2a;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--surface-1);color:var(--text-primary);
       font-family:"Pretendard","Malgun Gothic","Apple SD Gothic Neo",system-ui,sans-serif;
       font-size:15px;line-height:1.6;-webkit-font-smoothing:antialiased}
  .wrap{max-width:1080px;margin:0 auto;padding:40px 16px 80px;overflow-x:hidden}
  header h1{font-size:26px;margin:0 0 6px;letter-spacing:-.02em}
  header p{margin:0;color:var(--text-secondary);font-size:14px}
  .theme{position:fixed;top:12px;right:12px;background:var(--surface-2);color:var(--text-secondary);
         border:1px solid var(--border);border-radius:8px;padding:6px 10px;font-size:13px;cursor:pointer}
  section{margin-top:40px}
  h2{font-size:18px;margin:0 0 4px;letter-spacing:-.01em}
  .sub{color:var(--text-muted);font-size:13px;margin:0 0 16px}
  .card{background:var(--surface-2);border:1px solid var(--border);border-radius:14px;padding:18px 18px 14px}
  .grid{display:grid;gap:12px}
  .kpis{grid-template-columns:repeat(auto-fit,minmax(min(150px,100%),1fr))}
  .cols2{grid-template-columns:repeat(auto-fit,minmax(min(320px,100%),1fr))}
  .kpi .label{font-size:13px;color:var(--text-secondary);margin-bottom:4px}
  .kpi .num{font-size:30px;font-weight:650;letter-spacing:-.02em;font-variant-numeric:tabular-nums}
  .kpi .delta{font-size:12px;color:var(--text-muted);margin-top:4px}
  ul.summary{margin:0;padding-left:18px}
  ul.summary li{margin-bottom:8px;color:var(--text-primary)}
  table{width:100%;border-collapse:collapse;font-size:13.5px}
  th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--border)}
  th{color:var(--text-secondary);font-weight:600;font-size:12.5px;white-space:nowrap}
  td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
  details{margin-top:10px;overflow-x:auto}
  summary{cursor:pointer;color:var(--text-secondary);font-size:13px;padding:4px 0}
  .legend{display:flex;flex-wrap:wrap;gap:12px;margin:2px 0 10px;font-size:12.5px;color:var(--text-secondary)}
  .legend i{width:10px;height:10px;border-radius:3px;display:inline-block;margin-right:5px;vertical-align:-1px}
  .pill{display:inline-flex;align-items:center;gap:6px;font-size:12.5px;padding:2px 9px;border-radius:999px;
        border:1px solid var(--border);color:var(--text-secondary)}
  .dot{width:8px;height:8px;border-radius:50%;display:inline-block}
  .tip{position:fixed;pointer-events:none;background:var(--surface-1);color:var(--text-primary);
       border:1px solid var(--border);border-radius:8px;padding:7px 10px;font-size:12.5px;
       box-shadow:0 6px 20px rgba(0,0,0,.18);opacity:0;transition:opacity .08s;z-index:50;white-space:nowrap}
  .note{font-size:12.5px;color:var(--text-muted);margin-top:10px}
  .q{font-size:13px;color:var(--text-secondary);border-left:2px solid var(--border);padding:2px 0 2px 10px;margin:6px 0}
  footer{margin-top:48px;color:var(--text-muted);font-size:12.5px;border-top:1px solid var(--border);padding-top:16px}
  svg{display:block;width:100%;max-width:100%;height:auto;overflow:hidden}
  .ax{fill:var(--text-muted);font-size:11px}
  .lbl{fill:var(--text-secondary);font-size:11.5px}
  @media print{.theme{display:none}body{background:#fff}}
</style>
</head>
<body>
<button class="theme" onclick="toggleTheme()">라이트 / 다크</button>
<div class="wrap">
<header>
  <h1>__TITLE__</h1>
  <p>__SUBTITLE__</p>
</header>
__BODY__
<footer>
  분류는 키워드 규칙 기반 자동 분류라 개별 건에는 오차가 있을 수 있습니다. 사용자 이름은 아이디 앞 2자만 표기했고,
  질의어에 포함된 연락처·이메일·카드번호·주민번호는 마스킹했습니다. 직원 대화가 담긴 문서이므로 사내 공유 범위에 유의하세요.
  <br>생성 시각 __GENERATED__ · 분석 대상 레코드 __RECORDS__건 (__FIRST__ ~ __LAST__)
</footer>
</div>
<div class="tip" id="tip"></div>
<script>
const D = __DATA__;
const tip = document.getElementById('tip');
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const fmt = n => (n||0).toLocaleString('ko-KR');
function showTip(e, html){ tip.innerHTML = html; tip.style.opacity = 1;
  const x = Math.min(e.clientX + 14, innerWidth - tip.offsetWidth - 10);
  tip.style.left = x + 'px'; tip.style.top = (e.clientY - tip.offsetHeight - 12) + 'px'; }
function hideTip(){ tip.style.opacity = 0; }
function toggleTheme(){
  const dark = matchMedia('(prefers-color-scheme: dark)').matches;
  const cur = document.documentElement.getAttribute('data-theme') || (dark ? 'dark' : 'light');
  document.documentElement.setAttribute('data-theme', cur === 'dark' ? 'light' : 'dark');
  drawAll();
}
const SV = ['--s1','--s2','--s3','--s4','--s5','--s6','--s7','--s8'];
function el(tag, attrs, txt){ const n = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const k in attrs) n.setAttribute(k, attrs[k]); if (txt != null) n.textContent = txt; return n; }
function svgBox(host, h){ host.innerHTML = '';
  const w = Math.max(280, host.clientWidth || 600);
  const s = el('svg', {viewBox:`0 0 ${w} ${h}`, width:w, height:h, role:'img'}); host.appendChild(s);
  return {s, w, h}; }

/* 가로 막대 : 크기 비교 */
function barH(id, items, color){
  const host = document.getElementById(id); if (!host || !items.length) return;
  const rowH = 26, pad = 6, labelW = Math.min(190, Math.max(90, host.clientWidth * .34));
  const {s, w} = svgBox(host, items.length * rowH + pad * 2);
  const max = Math.max(...items.map(d => d.value)) || 1;
  const plot = w - labelW - 56;
  items.forEach((d, i) => {
    const y = pad + i * rowH, bw = Math.max(2, plot * d.value / max);
    s.appendChild(el('text', {x:labelW - 10, y:y + 16, 'text-anchor':'end', class:'lbl'}, d.name));
    const r = el('rect', {x:labelW, y:y + 5, width:bw, height:14, rx:4, fill:css(color || '--s1')});
    r.addEventListener('mousemove', e => showTip(e, `<b>${d.name}</b><br>${fmt(d.value)}건`));
    r.addEventListener('mouseleave', hideTip);
    s.appendChild(r);
    s.appendChild(el('text', {x:labelW + bw + 8, y:y + 16, class:'ax'}, fmt(d.value)));
  });
}

/* 세로 막대 : 기간별 비교 */
function colChart(id, items, unit){
  const host = document.getElementById(id); if (!host || !items.length) return;
  const h = 180, {s, w} = svgBox(host, h), bottom = 26, top = 14;
  const max = Math.max(...items.map(d => d.value)) || 1;
  const step = w / items.length, bw = Math.min(46, step * .58);
  s.appendChild(el('line', {x1:0, y1:h - bottom, x2:w, y2:h - bottom, stroke:css('--grid'), 'stroke-width':1}));
  items.forEach((d, i) => {
    const bh = Math.max(2, (h - bottom - top) * d.value / max);
    const x = i * step + (step - bw) / 2;
    const r = el('rect', {x, y:h - bottom - bh, width:bw, height:bh, rx:4, fill:css('--s1')});
    r.addEventListener('mousemove', e => showTip(e, `<b>${d.name}</b><br>${fmt(d.value)}${unit||'건'}` +
      (d.users != null ? `<br>사용자 ${fmt(d.users)}명` : '')));
    r.addEventListener('mouseleave', hideTip);
    s.appendChild(r);
    s.appendChild(el('text', {x:x + bw / 2, y:h - bottom + 15, 'text-anchor':'middle', class:'ax'}, d.name));
    s.appendChild(el('text', {x:x + bw / 2, y:h - bottom - bh - 5, 'text-anchor':'middle', class:'ax'}, fmt(d.value)));
  });
}

/* 선 그래프 : 일별 추이 (크로스헤어 + 툴팁) */
function lineChart(id, items){
  const host = document.getElementById(id); if (!host || !items.length) return;
  const h = 220, {s, w} = svgBox(host, h);
  const L = 38, R = 8, T = 12, B = 26, pw = w - L - R, ph = h - T - B;
  const max = Math.max(...items.map(d => d.value), 1);
  const X = i => L + (items.length === 1 ? pw / 2 : pw * i / (items.length - 1));
  const Y = v => T + ph - ph * v / max;
  for (let g = 0; g <= 2; g++){
    const y = T + ph * g / 2;
    s.appendChild(el('line', {x1:L, y1:y, x2:w - R, y2:y, stroke:css('--grid'), 'stroke-width':1}));
    s.appendChild(el('text', {x:L - 8, y:y + 4, 'text-anchor':'end', class:'ax'}, fmt(Math.round(max * (1 - g / 2)))));
  }
  const pts = items.map((d, i) => [X(i), Y(d.value)]);
  s.appendChild(el('path', {d:`M${L},${T + ph} ` + pts.map(p => `L${p[0]},${p[1]}`).join(' ') +
    ` L${X(items.length - 1)},${T + ph} Z`, fill:css('--s1'), opacity:.12}));
  s.appendChild(el('path', {d:'M' + pts.map(p => p.join(',')).join(' L'), fill:'none',
    stroke:css('--s1'), 'stroke-width':2, 'stroke-linejoin':'round'}));
  items.forEach((d, i) => { if (items.length <= 40 || i % Math.ceil(items.length / 15) === 0)
    s.appendChild(el('text', {x:X(i), y:h - 8, 'text-anchor':'middle', class:'ax'}, d.name.slice(8) || d.name)); });
  const cross = el('line', {y1:T, y2:T + ph, stroke:css('--text-muted'), 'stroke-width':1, opacity:0});
  const dot = el('circle', {r:4.5, fill:css('--s1'), stroke:css('--surface-2'), 'stroke-width':2, opacity:0});
  s.appendChild(cross); s.appendChild(dot);
  const hit = el('rect', {x:L, y:T, width:pw, height:ph, fill:'transparent'});
  hit.addEventListener('mousemove', e => {
    const bb = s.getBoundingClientRect();
    const rel = (e.clientX - bb.left) * (w / bb.width);
    const i = Math.max(0, Math.min(items.length - 1, Math.round((rel - L) / (pw / Math.max(1, items.length - 1)))));
    const d = items[i];
    cross.setAttribute('x1', X(i)); cross.setAttribute('x2', X(i)); cross.setAttribute('opacity', .5);
    dot.setAttribute('cx', X(i)); dot.setAttribute('cy', Y(d.value)); dot.setAttribute('opacity', 1);
    showTip(e, `<b>${d.name}</b><br>질의 ${fmt(d.value)}건<br>사용자 ${fmt(d.users)}명`);
  });
  hit.addEventListener('mouseleave', () => { hideTip(); cross.setAttribute('opacity', 0); dot.setAttribute('opacity', 0); });
  s.appendChild(hit);
}

/* 히트맵 : 단일 색상 5단계 */
function heatmap(id, matrix, rowLabels, colLabels, unit){
  const host = document.getElementById(id); if (!host) return;
  const flat = matrix.flat(), max = Math.max(...flat, 1);
  const rot = colLabels.some(c => c.length > 2);
  const L = 62, T = rot ? 56 : 18, pad = rot ? 46 : 6;
  const cell = Math.max(10, Math.min(28, ((host.clientWidth || 600) - L - pad) / colLabels.length));
  const {s, w} = svgBox(host, T + matrix.length * cell + 8);
  const ramp = ['--seq-0','--seq-1','--seq-2','--seq-3','--seq-4','--seq-5'];
  colLabels.forEach((c, j) => {
    const x = L + j * cell + cell / 2;
    if (rot){
      s.appendChild(el('text', {x, y:T - 8, class:'ax', 'text-anchor':'start',
        transform:`rotate(-45 ${x} ${T - 8})`}, c));
    } else if (colLabels.length <= 12 || j % 2 === 0){
      s.appendChild(el('text', {x, y:12, 'text-anchor':'middle', class:'ax'}, c));
    }
  });
  matrix.forEach((row, i) => {
    s.appendChild(el('text', {x:L - 8, y:T + i * cell + cell * .68, 'text-anchor':'end', class:'ax'}, rowLabels[i]));
    row.forEach((v, j) => {
      const idx = v === 0 ? 0 : 1 + Math.min(4, Math.floor(v / max * 4.999));
      const r = el('rect', {x:L + j * cell, y:T + i * cell, width:cell - 2, height:cell - 2, rx:3, fill:css(ramp[idx])});
      r.addEventListener('mousemove', e => showTip(e, `<b>${rowLabels[i]} · ${colLabels[j]}</b><br>${fmt(v)}${unit||'건'}`));
      r.addEventListener('mouseleave', hideTip);
      s.appendChild(r);
    });
  });
}

function drawAll(){
  lineChart('c-daily', D.daily);
  colChart('c-trend', D.trend);
  barH('c-cat', D.categories.map(c => ({name:c.name, value:c.value})));
  barH('c-users', D.top_users);
  barH('c-models', D.models, '--s3');
  barH('c-tools', D.tools, '--s2');
  barH('c-hours', D.hours.map((v, i) => ({name:String(i).padStart(2,'0') + '시', value:v})).filter(d => d.value > 0));
  heatmap('c-heat', D.heat, ['월','화','수','목','금','토','일'],
          Array.from({length:24}, (_, i) => String(i)), '건');
  if (D.matrix.length)
    heatmap('c-matrix', D.matrix.map(r => r.cells), D.matrix.map(r => r.user), D.top_cat_short, '건');
}
drawAll();
let t; addEventListener('resize', () => { clearTimeout(t); t = setTimeout(drawAll, 150); });
</script>
</body>
</html>
"""


def esc(text) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def kpi_tile(label: str, value, delta: str = "") -> str:
    val = f"{value:,}" if isinstance(value, int) else value
    return (f'<div class="card kpi"><div class="label">{esc(label)}</div>'
            f'<div class="num">{val}</div>'
            f'<div class="delta">{esc(delta)}</div></div>')


def table(headers: list[str], rows: list[list], nums: set[int] = frozenset()) -> str:
    head = "".join(f'<th class="{"num" if i in nums else ""}">{esc(h)}</th>' for i, h in enumerate(headers))
    body = ""
    for r in rows:
        body += "<tr>" + "".join(
            f'<td class="{"num" if i in nums else ""}">{c if isinstance(c, str) and c.startswith("<") else esc(c)}</td>'
            for i, c in enumerate(r)) + "</tr>"
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def chart_card(title: str, sub: str, chart_id: str, table_html: str = "", note: str = "") -> str:
    out = f'<div class="card"><h2>{esc(title)}</h2><p class="sub">{esc(sub)}</p><div id="{chart_id}"></div>'
    if table_html:
        out += f'<details><summary>표로 보기</summary>{table_html}</details>'
    if note:
        out += f'<p class="note">{esc(note)}</p>'
    return out + "</div>"


LEVEL_COLOR = {"good": "--good", "warn": "--warn", "serious": "--serious", "critical": "--critical"}
LEVEL_ICON = {"good": "●", "warn": "▲", "serious": "◆", "critical": "■"}
LEVEL_TEXT = {"good": "정상", "warn": "주의", "serious": "경고", "critical": "위험"}


def render_body(m: dict) -> str:
    k, p, pe = m["kpi"], m["prev"], m["personal"]
    parts = []

    # 1. KPI + 핵심 요약
    parts.append('<section><div class="grid kpis">'
                 + kpi_tile("활성 사용자", k["users"], delta_text(k["users"], p["users"]))
                 + kpi_tile("대화 수", k["convs"], delta_text(k["convs"], p["convs"]))
                 + kpi_tile("질의 수", k["queries"], delta_text(k["queries"], p["queries"]))
                 + kpi_tile("1인당 평균 질의", f"{k['per_user']}건", f"대화당 질의 중간값 {k['median_conv']}건")
                 + kpi_tile("상위 10명 점유율", f"{k['top10_share']}%", f"상위 20명 {k['top20_share']}%")
                 + kpi_tile("예약·자동작업 질의", k["auto"], "사용자 통계에서 분리 집계")
                 + "</div></section>")
    parts.append('<section><div class="card"><h2>핵심 요약</h2><p class="sub">이 달의 사용 현황을 한눈에</p>'
                 '<ul class="summary">' + "".join(f"<li>{esc(s)}</li>" for s in summary_lines(m))
                 + "</ul></div></section>")

    # 2. 사용 추이
    parts.append('<section><div class="grid cols2">'
                 + chart_card("일별 질의 추이", f"{m['period_label']} · KST 기준", "c-daily",
                              table(["날짜", "질의", "사용자"],
                                    [[d["name"], f"{d['value']:,}", f"{d['users']:,}"] for d in m["daily"]], {1, 2}))
                 + chart_card("월별 질의 추이", "최근 6개월", "c-trend",
                              table(["월", "질의", "사용자"],
                                    [[d["name"], f"{d['value']:,}", f"{d['users']:,}"] for d in m["trend"]], {1, 2}))
                 + "</div></section>")

    # 3. 시간대
    parts.append('<section><div class="grid cols2">'
                 + chart_card("요일 × 시간대 분포", "색이 진할수록 질의가 많음 (KST)", "c-heat")
                 + chart_card("시간대별 질의", "0~23시 (KST)", "c-hours")
                 + "</div></section>")

    # 4. 카테고리
    cat_table = table(["카테고리", "질의", "비중", "대화"],
                      [[c["name"], f"{c['value']:,}", f"{c['share']}%", f"{c['convs']:,}"] for c in m["categories"]],
                      {1, 2, 3})
    parts.append("<section>" + chart_card(
        "질의 카테고리 분포", "대화 단위로 주된 작업 1개를 판정해 그 대화의 모든 질의에 적용 · 예약·자동작업 포함", "c-cat", cat_table,
        "키워드 규칙 기반 자동 분류입니다. 더 정확한 분류가 필요하면 Claude 에 로그 파일과 함께 "
        "chatgpt-usage-log-report 스킬로 재분류를 요청하세요.") + "</section>")

    # 5. 상위 사용자
    parts.append('<section><div class="grid cols2">'
                 + chart_card("상위 사용자 질의 수", "상위 15명 · 아이디 앞 2자만 표기", "c-users",
                              table(["사용자", "질의"], [[u["name"], f"{u['value']:,}"] for u in m["top_users"]], {1}))
                 + chart_card("상위 사용자 × 카테고리", "상위 10명이 어떤 용도로 쓰는지", "c-matrix",
                              table(["사용자"] + m["top_cat_names"] + ["합계"],
                                    [[r["user"]] + [f"{v:,}" for v in r["cells"]] + [f"{r['total']:,}"]
                                     for r in m["matrix"]],
                                    set(range(1, len(m["top_cat_names"]) + 2))))
                 + "</div></section>")

    # 6. 개인 목적 사용 진단
    verdict = ("소수 인원에 집중된 양상입니다." if pe["top5_share"] >= 50
               else "특정 인원 집중보다는 넓게 퍼져 있습니다.")
    parts.append('<section><div class="card"><h2>개인 목적 사용 진단</h2>'
                 f'<p class="sub">개인 질의 {pe["count"]:,}건 · 전체의 {pe["share"]}% · {verdict}</p>'
                 + table(["점검 항목", "값"], [
                     ["개인 질의 비중", f"{pe['share']}% ({pe['count']:,}건)"],
                     ["개인 질의를 한 인원", f"{pe['users']:,}명"],
                     ["20건 이상 사용자 중 개인 비중 50% 이상", f"{pe['over50']}명 / {pe['heavy_users']}명"],
                     ["20건 이상 사용자 중 개인 비중 30% 이상", f"{pe['over30']}명 / {pe['heavy_users']}명"],
                     ["상위 5명이 차지한 개인 질의 비중", f"{pe['top5_share']}%"],
                     ["개인 질의 중 평일 근무시간(09~18시) 발생", f"{pe['worktime_share']}%"],
                 ], {1})
                 + '<p class="note">개인 질의에는 업무와 관련된 일반 상식 질문이 섞여 있습니다. '
                   '수치는 경향 파악용이며 개별 건의 성격은 다를 수 있습니다.</p></div></section>')

    # 7. 모델 · 도구 · 채택률
    adopt = []
    for label, items in (("맞춤 GPT", m["gpts"]), ("프로젝트", m["projects"]),
                         ("스킬", m["skills"]), ("첨부 파일 확장자", m["exts"]), ("클라이언트", m["clients"])):
        if items:
            adopt.append([label, ", ".join(f"{i['name']} {i['value']:,}" for i in items[:5])])
    parts.append('<section><div class="grid cols2">'
                 + chart_card("모델별 사용량", "응답 생성에 사용된 모델", "c-models",
                              table(["모델", "건수"], [[i["name"], f"{i['value']:,}"] for i in m["models"]], {1}))
                 + chart_card("도구 사용량", "검색·코드 실행·이미지 생성 등", "c-tools",
                              table(["도구", "건수"], [[i["name"], f"{i['value']:,}"] for i in m["tools"]], {1}))
                 + "</div>"
                 + ('<div class="card" style="margin-top:12px"><h2>기능 채택 현황</h2>'
                    '<p class="sub">맞춤 GPT · 프로젝트 · 스킬 · 첨부</p>' + table(["항목", "상위 사용"], adopt)
                    + "</div>" if adopt else "")
                 + "</section>")

    # 8. 보안 점검
    sec_rows = []
    for s in m["security"]:
        level = s["level"] if s["hits"] else "good"
        badge = (f'<span class="pill"><span style="color:var({LEVEL_COLOR[level]});font-size:11px">'
                 f'{LEVEL_ICON[level]}</span>{LEVEL_TEXT[level]}</span>')
        sec_rows.append([s["item"], f"{s['hits']:,}", f"{s['people']:,}" if s["people"] else "-", badge])
    parts.append('<section><div class="card"><h2>보안 점검</h2>'
                 f'<p class="sub">인증 로그 {m["auth_count"]:,}건 포함 · 건수와 인원만 집계하고 원문은 표시하지 않습니다</p>'
                 + table(["점검 항목", "건수", "인원", "상태"], sec_rows, {1, 2})
                 + ('<p class="note">접속 국가: '
                    + ", ".join(f"{c['name']} {c['value']:,}" for c in m["countries"]) + "</p>"
                    if m["countries"] else "")
                 + "</div></section>")

    # 9. 질의어 샘플
    if m["samples"]:
        blocks = ""
        for s in m["samples"]:
            items = "".join(f'<div class="q"><b>{esc(i["cat"])}</b> · {esc(i["ts"])}<br>{esc(i["text"])}</div>'
                            for i in s["items"])
            blocks += (f'<details><summary>{esc(s["user"])} · 질의 {s["total"]:,}건</summary>'
                       + (items or '<p class="note">표시할 샘플이 없습니다.</p>') + "</details>")
        parts.append('<section><div class="card"><h2>상위 사용자 질의어 샘플</h2>'
                     '<p class="sub">개인 생활 카테고리 제외 · 기간 전체에서 균등 추출 · 개인정보 마스킹</p>'
                     + blocks + "</div></section>")
    return "\n".join(parts)


def render(m: dict) -> str:
    title = f"ChatGPT 사용 로그 분석 리포트 — {m['period_label']}"
    sub = (f"분석 기간 {m['period']}-01 ~ {m['period']}-{calendar.monthrange(int(m['period'][:4]), int(m['period'][5:7]))[1]}"
           f" (KST) · 활성 사용자 {m['kpi']['users']:,}명 · 질의 {m['kpi']['queries']:,}건")
    return (HTML.replace("__TITLE__", esc(title))
            .replace("__SUBTITLE__", esc(sub))
            .replace("__BODY__", render_body(m))
            .replace("__GENERATED__", m["generated"])
            .replace("__RECORDS__", f"{m['coverage']['records']:,}")
            .replace("__FIRST__", m["coverage"]["first"])
            .replace("__LAST__", m["coverage"]["last"])
            .replace("__DATA__", json.dumps(m, ensure_ascii=False)))


# ---------------------------------------------------------------- 진입점

def default_period() -> str:
    today = datetime.now(KST)
    if today.day == calendar.monthrange(today.year, today.month)[1]:
        return f"{today:%Y-%m}"
    prev = today.replace(day=1) - timedelta(days=1)
    return f"{prev:%Y-%m}"


def main() -> int:
    ap = argparse.ArgumentParser(description="ChatGPT 사용 로그 월간 분석 리포트 생성기")
    ap.add_argument("--base", default=".", help="로그 파일을 찾을 폴더 (기본: 현재 폴더)")
    ap.add_argument("--input", nargs="*", default=[], help="분석할 파일을 직접 지정")
    ap.add_argument("--period", default=None, help="분석 대상 월 (YYYY-MM)")
    ap.add_argument("--out", default=None, help="리포트 저장 폴더 (기본: <base>/reports)")
    args = ap.parse_args()

    base = os.path.abspath(args.base)
    period = args.period or default_period()
    if not re.fullmatch(r"\d{4}-\d{2}", period):
        log(f"period 형식이 잘못되었습니다: {period}")
        return 2
    out_dir = os.path.abspath(args.out or os.path.join(base, "reports"))
    os.makedirs(out_dir, exist_ok=True)

    paths = [os.path.abspath(p) for p in args.input if os.path.isfile(p)] or find_data_files(base)
    if not paths:
        log(f"분석할 로그 파일을 찾지 못했습니다. (폴더: {base})")
        return 4
    log(f"대상 파일 {len(paths)}개 · 분석 월 {period}")

    records = load_records(paths[:20])
    if not records:
        log("로그 파일은 찾았지만 읽어낸 레코드가 없습니다. 파일 형식을 확인하세요.")
        return 5

    model = build_model(records, period)
    if model["kpi"]["queries"] == 0:
        log(f"경고: {period} 구간에 질의가 없습니다. (데이터 범위 {model['coverage']['first']} ~ {model['coverage']['last']})")

    out_path = os.path.join(out_dir, f"chatgpt_usage_{period}.html")
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(render(model))
    log(f"리포트 생성 완료: {out_path}")
    for line in summary_lines(model):
        log("  · " + line)
    print(f"REPORT={out_path}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
