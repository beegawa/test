"""회사 ChatGPT 대화 로그 웹 콘솔 (Flask).

  127.0.0.1 에서만 뜨는 로컬 웹 앱. 관리자 키는 최초 1회만 입력받아
  OS 자격 증명 저장소에 보관하고, 받은 로그는 SQLite 에 누적한다.

  실행:  python app.py            → http://127.0.0.1:5000 자동 오픈
"""

from __future__ import annotations

import argparse
import logging
import threading
import webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory

import keystore
from collector import EVENT_TYPE_CHECKED_META, CollectResult, collect, resolve_event_types
from compliance import AuthError, ComplianceClient, ComplianceError, ForbiddenError, to_iso
from settings import (
    DEFAULT_MAX_LOGS,
    ORG_ID,
    PREVIEW_LIMIT,
    RETENTION_DAYS,
    WORKSPACE_ID,
    db_path,
)
from records import PARSER_VERSION, normalize
from store import LogStore
from xlsx_export import build_workbook_bytes

log = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).resolve().parent / "static"


# ------------------------------------------------------------------ 수집 작업
class PullJob:
    """수집은 몇 분씩 걸릴 수 있어 백그라운드 스레드로 돌리고 진행률을 화면이 조회한다."""

    def __init__(self):
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()
        self.state: dict = {"running": False, "progress": None, "result": None, "error": None, "params": None}

    @property
    def running(self) -> bool:
        with self._lock:
            return bool(self.state["running"])

    def start(self, worker, params: dict) -> None:
        with self._lock:
            if self.state["running"]:
                raise RuntimeError("이미 수집이 진행 중입니다.")
            self._cancel = threading.Event()
            self.state = {"running": True, "progress": None, "result": None, "error": None, "params": params}
            self._thread = threading.Thread(target=self._run, args=(worker,), daemon=True)
            self._thread.start()

    def _run(self, worker) -> None:
        try:
            result: CollectResult = worker(self._progress, self._cancel)
            with self._lock:
                self.state["result"] = result.to_dict()
        except (ComplianceError, RuntimeError) as exc:
            log.error("수집 실패: %s", exc)
            with self._lock:
                self.state["error"] = str(exc)
        except Exception as exc:  # pragma: no cover - 예기치 못한 오류도 화면에 남긴다
            log.exception("수집 중 예기치 못한 오류")
            with self._lock:
                self.state["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            with self._lock:
                self.state["running"] = False
                self.state["cancelled"] = self._cancel.is_set()

    def _progress(self, snapshot: dict) -> None:
        with self._lock:
            self.state["progress"] = snapshot

    def cancel(self) -> None:
        self._cancel.set()

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self.state)


# ------------------------------------------------------------------ 앱
def create_app(*, database: str | Path | None = None, client_factory=None) -> Flask:
    app = Flask(__name__, static_folder=None)
    app.config["STORE"] = LogStore(database or db_path())
    # 파서가 바뀌었으면 저장된 원본을 다시 해석한다(다시 내려받지 않는다).
    갱신 = app.config["STORE"].ensure_parsed(normalize, PARSER_VERSION)
    if 갱신:
        log.info("기존 로그 %d건을 새 파서로 다시 해석했습니다.", 갱신)
    app.config["JOB"] = PullJob()
    app.config["CLIENT_FACTORY"] = client_factory or (lambda key: ComplianceClient(key))
    app.config["LAST_QUERY"] = {}

    def store() -> LogStore:
        return app.config["STORE"]

    def job() -> PullJob:
        return app.config["JOB"]

    def make_client() -> ComplianceClient:
        key = keystore.load_key()
        if not key:
            raise AuthError("관리자 키가 저장돼 있지 않습니다. 먼저 키를 저장하세요.")
        return app.config["CLIENT_FACTORY"](key)

    # -------------------------------------------------------------- 화면
    @app.get("/")
    def index() -> Response:
        return send_from_directory(STATIC_DIR, "index.html")

    @app.get("/static/<path:name>")
    def static_files(name: str) -> Response:
        return send_from_directory(STATIC_DIR, name)

    # -------------------------------------------------------------- 상태/키
    @app.get("/api/status")
    def api_status():
        location = keystore.where()
        return jsonify(
            {
                "key_saved": bool(location),
                "key_location": location,
                "workspace_id": WORKSPACE_ID,
                "org_id": ORG_ID,
                "scope": f"organization:{ORG_ID}" if ORG_ID else f"workspace:{WORKSPACE_ID}",
                "retention_days": RETENTION_DAYS,
                "db_path": str(store().path),
                "stats": store().stats(),
                "event_types": store().get_meta("event_types") or [],
                "event_types_checked_at": store().get_meta(EVENT_TYPE_CHECKED_META) or "",
                "pull": job().snapshot(),
            }
        )

    @app.post("/api/save-key")
    def api_save_key():
        key = (request.get_json(silent=True) or {}).get("key", "")
        if not str(key).strip():
            return jsonify({"ok": False, "error": "키를 입력하세요."}), 400
        # 저장 전에 실제 API 로 검증한다. 401/403 이면 저장하지 않는다.
        try:
            info = app.config["CLIENT_FACTORY"](str(key).strip()).validate()
        except (AuthError, ForbiddenError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 401
        except ComplianceError as exc:
            return jsonify({"ok": False, "error": f"키를 확인하지 못했습니다. {exc}"}), 502
        location = keystore.save_key(str(key).strip())
        log.info("관리자 키를 저장했습니다. (%s, %s)", location, keystore.mask(str(key)))
        return jsonify({"ok": True, "key_location": location, "scope": info.get("scope")})

    @app.post("/api/forget-key")
    def api_forget_key():
        removed = keystore.forget_key()
        return jsonify({"ok": True, "removed": removed})

    @app.post("/api/detect-event-types")
    def api_detect_event_types():
        try:
            types = resolve_event_types(make_client(), store(), force=True)
        except (AuthError, ForbiddenError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 401
        except ComplianceError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 502
        return jsonify({"ok": True, "event_types": types})

    # -------------------------------------------------------------- 수집
    @app.post("/api/pull")
    def api_pull():
        payload = request.get_json(silent=True) or {}
        days = _int(payload.get("days"), default=1, low=1, high=RETENTION_DAYS)
        incremental = bool(payload.get("incremental"))
        max_logs = _int(payload.get("max_logs"), default=DEFAULT_MAX_LOGS, low=1, high=1_000_000)
        try:
            client = make_client()
        except AuthError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 401

        def worker(progress, cancel) -> CollectResult:
            return collect(
                client,
                store(),
                days=None if incremental else days,
                incremental=incremental,
                max_logs=max_logs,
                progress=progress,
                cancel=cancel,
            )

        try:
            job().start(worker, {"days": days, "incremental": incremental, "max_logs": max_logs})
        except RuntimeError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 409
        return jsonify({"ok": True, "started": True, "pull": job().snapshot()}), 202

    @app.get("/api/pull/status")
    def api_pull_status():
        state = job().snapshot()
        body = {"ok": True, "pull": state, "stats": store().stats()}
        if not state["running"] and state.get("result"):
            body["preview"], body["preview_total"] = _preview(store(), state)
        return jsonify(body)

    @app.post("/api/pull/cancel")
    def api_pull_cancel():
        job().cancel()
        return jsonify({"ok": True})

    # -------------------------------------------------------------- 검색
    @app.get("/api/search")
    def api_search():
        query = _query_from_request()
        app.config["LAST_QUERY"] = query
        rows = store().search(**query, limit=PREVIEW_LIMIT)
        return jsonify(
            {
                "ok": True,
                "count": len(rows),
                "total": store().count(**query),
                "preview_limit": PREVIEW_LIMIT,
                "rows": [_row_view(row) for row in rows],
                "query": query,
            }
        )

    @app.get("/api/users")
    def api_users():
        return jsonify({"ok": True, "users": store().users()})

    @app.get("/api/log/<path:log_id>")
    def api_log_detail(log_id: str):
        row = store().get(log_id)
        if row is None:
            return jsonify({"ok": False, "error": "해당 로그를 찾지 못했습니다."}), 404
        return jsonify({"ok": True, "row": row})

    # -------------------------------------------------------------- 엑셀
    @app.get("/api/download.xlsx")
    def api_download():
        query = _query_from_request() if request.args else (app.config.get("LAST_QUERY") or {})
        limit = _int(request.args.get("limit"), default=100_000, low=1, high=1_000_000)
        rows = store().search(**query, limit=limit)
        try:
            payload = build_workbook_bytes(rows)
        except RuntimeError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 500
        name = f"chatgpt_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        return Response(
            payload,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )

    return app


# ------------------------------------------------------------------ 보조
def _int(value, *, default: int, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def _query_from_request() -> dict:
    args = request.args
    return {
        "start": (args.get("from") or "").strip() or None,
        "end": (args.get("to") or "").strip() or None,
        "user": (args.get("user") or "").strip() or None,
        "keyword": (args.get("q") or "").strip() or None,
        "event_type": (args.get("event_type") or "").strip() or None,
        "conversation_id": (args.get("conversation_id") or "").strip() or None,
    }


def _since_for(params: dict) -> str | None:
    days = params.get("days")
    if params.get("incremental") or not days:
        return None
    return to_iso(datetime.now(timezone.utc) - timedelta(days=int(days)))


def _preview(store: LogStore, state: dict) -> tuple[list[dict], int]:
    """수집 직후 표에 보여줄 것.

    이번 수집에서 새로 들어온 것을 먼저 보여주고, 전부 중복이라 새로 들어온 게
    없으면 요청한 기간의 저장분을 보여준다(표가 비어 보이지 않도록).
    """
    started = (state.get("result") or {}).get("started_at")
    if started:
        query = {"fetched_since": started}
        rows = store.search(**query, limit=PREVIEW_LIMIT)
        if rows:
            return [_row_view(row) for row in rows], store.count(**query)
    query = {"start": _since_for(state.get("params") or {})}
    return (
        [_row_view(row) for row in store.search(**query, limit=PREVIEW_LIMIT)],
        store.count(**query),
    )


def _row_view(row: dict) -> dict:
    """화면 표에 필요한 것만. raw 는 자세히 보기에서만 쓰도록 길이를 줄인다."""
    view = {key: row.get(key, "")
            for key in ("id", "event_type", "ts", "user", "action", "conversation_id", "summary")}
    view["content"] = (row.get("content") or "")[:4000]
    return view


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="회사 ChatGPT 대화 로그 웹 콘솔")
    parser.add_argument("--host", default="127.0.0.1", help="기본 127.0.0.1 (내 PC 에서만 접속)")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--db", help="SQLite 파일 경로")
    parser.add_argument("--no-open", action="store_true", help="브라우저를 자동으로 열지 않음")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    app = create_app(database=args.db)
    url = f"http://{'127.0.0.1' if args.host in ('', '0.0.0.0') else args.host}:{args.port}"

    if args.host not in ("127.0.0.1", "localhost"):
        log.warning(
            "외부에서 접속 가능한 주소로 띄웁니다(%s). 대화 내용이 담기는 화면이므로 "
            "사내 인증·HTTPS·접근 로그를 반드시 앞에 두세요.",
            args.host,
        )

    print()
    print("  회사 ChatGPT 대화 로그 웹 콘솔")
    print(f"  →  {url}")
    print(f"  DB: {app.config['STORE'].path}")
    print("  이 창을 닫으면 종료됩니다.")
    print()

    if not args.no_open:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host=args.host, port=args.port, debug=False, threaded=True)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
