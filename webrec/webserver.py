"""내 PC 에서 띄우는 예약 녹화 웹 서버.

브라우저에서 '주소 + 시간' 만 넣으면 예약이 등록되고, 시간이 되면
기존 녹화 엔진(10초 샘플링 점검 -> 녹화 -> 검증 -> 메일)이 그대로 돌아간다.
추가 설치가 필요 없도록 파이썬 표준 라이브러리만 사용한다.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import threading
import traceback
from datetime import datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

from .config import NotifyConfig, SmtpConfig, format_duration, smtp_from_env
from .errors import ConfigError, WebrecError
from .notify import Mailer, preflight_body
from .preflight import run_preflight
from .runner import JobRunner
from .schedule import next_run
from .store import (
    ACTIVE_STATUSES,
    STAGE_TO_STATUS,
    STATUS_CHECKING,
    STATUS_DISABLED,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_MISSED,
    STATUS_RECORDING,
    STATUS_SCHEDULED,
    JobRecord,
    JobStore,
)
from .tools import tool_report

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
MEDIA_SUFFIXES = (".mkv", ".mp4", ".webm", ".ts")

POLL_SECONDS = 2           # 예약 확인 주기
MIN_SALVAGE_SECONDS = 30   # 지각 시작 시 이만큼도 안 남았으면 포기 (짧은 녹화는 길이의 절반)


# ============================================================== 예약 실행기
class WebScheduler:
    """등록된 예약을 지켜보다 때가 되면 녹화를 실행한다."""

    def __init__(self, app: "WebrecApp"):
        self.app = app
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._running: set[str] = set()
        self._lock = threading.Lock()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="webrec-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    @property
    def busy(self) -> bool:
        with self._lock:
            return bool(self._running)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:  # 한 번의 오류로 예약 감시가 멈추면 안 된다
                log.exception("예약 확인 중 오류")
            self._stop.wait(POLL_SECONDS)

    # ------------------------------------------------------------------ 판단
    def tick(self) -> None:
        for record in self.app.store.list():
            with self._lock:
                if record.id in self._running:
                    continue
            if not record.enabled or record.status in ACTIVE_STATUSES:
                continue
            try:
                job = record.to_job()
            except ConfigError as exc:
                self.app.store.update(record.id, status=STATUS_FAILED, message=f"설정 오류: {exc}")
                continue

            decision = self._due(record, job)
            if decision is None:
                continue
            scheduled, duration, note = decision
            self._launch(record, scheduled, duration, note)

    def _due(self, record: JobRecord, job) -> tuple[datetime | None, int, str] | None:
        """지금 실행해야 하면 (예약시각, 녹화길이, 안내문) 을 돌려준다."""
        tz = job.tzinfo
        now = datetime.now(tz)
        lead = job.preflight.lead_seconds if job.preflight.enabled else 0

        if job.start is not None:
            scheduled = job.start.replace(tzinfo=tz) if job.start.tzinfo is None and tz else job.start
            if scheduled.tzinfo is None:
                now = datetime.now()
            late = (now - scheduled).total_seconds()

            if late < -lead:
                return None                                   # 아직 멀었다
            if late <= 0:
                return scheduled, job.duration, ""            # 점검 시작 구간
            remaining = int(job.duration - late)
            salvage_floor = min(MIN_SALVAGE_SECONDS, job.duration / 2)
            if remaining >= salvage_floor:                    # 늦게 켰어도 남은 만큼은 녹화
                return None, remaining, (
                    f"예약 시각({scheduled:%H:%M})이 지나 남은 {format_duration(remaining)}만 녹화합니다."
                )
            if record.status not in (STATUS_DONE, STATUS_FAILED, STATUS_MISSED):
                self.app.store.update(
                    record.id,
                    status=STATUS_MISSED,
                    message=f"예약 시각 {scheduled:%Y-%m-%d %H:%M} 이 지났습니다 (프로그램이 꺼져 있었습니다).",
                )
            return None

        upcoming = next_run(job)
        if upcoming is None:
            return None
        if (upcoming - now).total_seconds() <= lead:
            return upcoming, job.duration, ""
        return None

    # ------------------------------------------------------------------ 실행
    def _launch(self, record: JobRecord, scheduled: datetime | None, duration: int, note: str) -> None:
        with self._lock:
            if record.id in self._running:
                return
            self._running.add(record.id)
        thread = threading.Thread(
            target=self._run,
            args=(record.id, scheduled, duration, note),
            name=f"webrec-job-{record.id}",
            daemon=True,
        )
        thread.start()

    def _run(self, job_id: str, scheduled: datetime | None, duration: int, note: str) -> None:
        store = self.app.store
        try:
            record = store.get(job_id)
            if record is None:
                return
            job = record.to_job()
            job.duration = duration
            job.output_dir = self.app.output_dir

            store.update(
                job_id,
                status=STATUS_CHECKING if job.preflight.enabled else STATUS_RECORDING,
                message=note,
                started_at=None,
                duration_sec=duration,
            )

            def progress(stage: str, outcome) -> None:
                fields: dict = {"status": STAGE_TO_STATUS.get(stage, record.status)}
                if stage == "녹화":
                    fields["started_at"] = datetime.now().isoformat(timespec="seconds")
                store.update(job_id, **fields)

            runner = JobRunner(
                job, self.app.mailer(), log_dir=self.app.log_dir, progress=progress
            )
            outcome = runner.run(scheduled_at=scheduled)
            store.add_run(job_id, _run_summary(outcome))

            is_repeating = bool(job.cron)
            store.update(
                job_id,
                status=(STATUS_SCHEDULED if is_repeating else (STATUS_DONE if outcome.ok else STATUS_FAILED)),
                message=(
                    f"완료: {Path(outcome.output_path).name}" if outcome.ok and outcome.output_path
                    else (outcome.error or "")
                ),
                started_at=None,
            )
        except Exception as exc:  # pragma: no cover - 예상 못 한 오류
            log.exception("[%s] 예약 실행 중 오류", job_id)
            store.update(job_id, status=STATUS_FAILED, message=f"{type(exc).__name__}: {exc}", started_at=None)
        finally:
            with self._lock:
                self._running.discard(job_id)

    # -------------------------------------------------------- 즉시 10초 점검
    def check_now(self, job_id: str) -> None:
        with self._lock:
            if job_id in self._running:
                raise WebrecError("이미 실행 중인 작업입니다.")
            self._running.add(job_id)
        threading.Thread(
            target=self._check, args=(job_id,), name=f"webrec-check-{job_id}", daemon=True
        ).start()

    def _check(self, job_id: str) -> None:
        store = self.app.store
        try:
            record = store.get(job_id)
            if record is None:
                return
            job = record.to_job()
            job.output_dir = self.app.output_dir
            store.update(job_id, status=STATUS_CHECKING, message="10초 샘플로 점검 중입니다...")

            report = run_preflight(job)
            store.add_run(job_id, {
                "kind": "점검",
                "ok": report.ok,
                "at": datetime.now().isoformat(timespec="seconds"),
                "error": report.error,
                "summary": report.summary(),
            })
            store.update(
                job_id,
                status=(STATUS_SCHEDULED if record.enabled else STATUS_DISABLED),
                message=("점검 정상 - 녹화 가능합니다." if report.ok else f"점검 실패: {report.error}"),
            )
            if not report.ok or job.notify.events:
                notify = job.notify
                subject = f"사전 점검 {'정상' if report.ok else '실패'} - {job.name}"
                self.app.mailer().send(notify, subject, preflight_body(job, report))
        except Exception as exc:
            log.exception("[%s] 점검 중 오류", job_id)
            store.update(job_id, status=STATUS_FAILED, message=f"점검 오류: {exc}")
        finally:
            with self._lock:
                self._running.discard(job_id)


def _run_summary(outcome) -> dict:
    """실행 결과를 화면/저장용으로 요약."""
    verification = outcome.verification
    return {
        "kind": "녹화",
        "ok": outcome.ok,
        "at": outcome.started_at.isoformat(timespec="seconds"),
        "finished_at": outcome.finished_at.isoformat(timespec="seconds"),
        "stage": outcome.stage,
        "error": outcome.error,
        "output": str(outcome.output_path) if outcome.output_path else None,
        "file": Path(outcome.output_path).name if outcome.output_path else None,
        "size_bytes": (verification.metrics.get("size_bytes") if verification else None),
        "duration_sec": (verification.metrics.get("duration_sec") if verification else None),
        "warnings": list(outcome.warnings),
        "summary": verification.summary() if verification else None,
        "preflight": (outcome.preflight.summary() if outcome.preflight else None),
        "preflight_ok": (outcome.preflight.ok if outcome.preflight else None),
    }


# ==================================================================== 앱
class WebrecApp:
    """저장소 + 예약 실행기 + 설정을 묶은 것."""

    def __init__(self, *, data_dir: Path, output_dir: Path, log_dir: Path):
        self.data_dir = Path(data_dir)
        self.output_dir = Path(output_dir)
        self.log_dir = Path(log_dir)
        for directory in (self.data_dir, self.output_dir, self.log_dir):
            directory.mkdir(parents=True, exist_ok=True)
        self.store = JobStore(self.data_dir / "jobs.json")
        self.scheduler = WebScheduler(self)

    # ------------------------------------------------------------------ 메일
    def smtp(self) -> SmtpConfig:
        """저장된 설정이 있으면 그것을, 없으면 환경변수를 쓴다."""
        saved = self.store.settings.get("smtp") or {}
        if saved.get("host"):
            return SmtpConfig(
                host=saved.get("host", ""),
                port=int(saved.get("port") or 587),
                username=saved.get("username", ""),
                password=saved.get("password", ""),
                sender=saved.get("sender") or saved.get("username", ""),
                starttls=bool(saved.get("starttls", True)),
                ssl=bool(saved.get("ssl", False)),
            )
        return smtp_from_env()

    def mailer(self) -> Mailer:
        return Mailer(self.smtp())

    def default_recipient(self) -> str:
        return self.store.settings.get("notify_to") or "travislee@shinwon.com"

    # ------------------------------------------------------------------ 상태
    def state(self) -> dict:
        jobs = []
        for record in sorted(self.store.list(), key=lambda r: r.created_at, reverse=True):
            jobs.append(self._job_view(record))

        smtp = self.smtp()
        return {
            "now": datetime.now().isoformat(timespec="seconds"),
            "jobs": jobs,
            "recordings": self.recordings(),
            "output_dir": str(self.output_dir.resolve()),
            "mail": {
                "configured": smtp.configured,
                "host": smtp.host,
                "port": smtp.port,
                "username": smtp.username,
                "sender": smtp.sender,
                "starttls": smtp.starttls,
                "ssl": smtp.ssl,
                "has_password": bool(smtp.password),
                "to": self.default_recipient(),
            },
            "tools": tool_report(),
        }

    def _job_view(self, record: JobRecord) -> dict:
        spec = record.spec
        view = {
            "id": record.id,
            "name": record.name,
            "url": spec.get("url", ""),
            "status": record.status,
            "message": record.message,
            "enabled": record.enabled,
            "start": spec.get("start"),
            "cron": spec.get("cron"),
            "backend": spec.get("backend", "auto"),
            "started_at": record.started_at,
            "duration_sec": record.duration_sec,
            "runs": record.runs[:5],
            "next_run": None,
            "duration_label": "",
            "error": None,
        }
        try:
            job = record.to_job()
            view["duration_label"] = format_duration(job.duration)
            view["duration_sec_planned"] = job.duration
            view["preflight"] = {
                "enabled": job.preflight.enabled,
                "duration": job.preflight.duration,
                "lead_seconds": job.preflight.lead_seconds,
            }
            view["notify_to"] = job.notify.to
            upcoming = next_run(job)
            if upcoming is not None:
                view["next_run"] = upcoming.isoformat(timespec="seconds")
        except ConfigError as exc:
            view["error"] = str(exc)
        return view

    def recordings(self) -> list[dict]:
        files = []
        if self.output_dir.is_dir():
            for path in self.output_dir.iterdir():
                if path.is_file() and path.suffix.lower() in MEDIA_SUFFIXES:
                    stat = path.stat()
                    files.append({
                        "name": path.name,
                        "size_bytes": stat.st_size,
                        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                        # 한글 파일명도 그대로 쓸 수 있도록 인코딩해서 내보낸다
                        "url": f"/recordings/{quote(path.name)}",
                    })
        return sorted(files, key=lambda item: item["modified"], reverse=True)

    # ------------------------------------------------------------------ 예약
    def create_job(self, payload: dict) -> dict:
        """웹 폼에서 온 값을 작업 정의로 바꿔 저장한다."""
        url = (payload.get("url") or "").strip()
        if not url:
            raise ConfigError("녹화할 주소를 입력하세요.")

        duration = (payload.get("duration") or "").strip()
        if not duration:
            raise ConfigError("녹화 길이를 입력하세요. (예: 1h30m, 90m)")

        repeat = (payload.get("repeat") or "once").strip()
        spec: dict = {
            "name": (payload.get("name") or "").strip() or _name_from_url(url),
            "url": url,
            "duration": duration,
            "backend": payload.get("backend") or "auto",
            "remux_mp4": bool(payload.get("remux_mp4")),
            "notify": {
                "to": payload.get("notify_to") or self.default_recipient(),
                "on": ["preflight_failed", "started", "completed", "failed"],
            },
            "preflight": {
                "enabled": payload.get("preflight_enabled", True),
                "duration": int(payload.get("preflight_duration") or 10),
                "lead_seconds": int(payload.get("preflight_lead") or 300),
                "abort_on_failure": bool(payload.get("abort_on_failure")),
            },
            "video": {
                "resolution": payload.get("resolution") or "1280x720",
                "fps": int(payload.get("fps") or 25),
                "audio": bool(payload.get("audio", True)),
            },
        }
        if payload.get("timezone"):
            spec["timezone"] = payload["timezone"]

        browser = {
            key: payload.get(key)
            for key in ("display_name", "email", "passcode")
            if (payload.get(key) or "").strip()
        }
        if browser:
            spec["browser"] = browser

        if repeat == "once":
            start = (payload.get("start") or "").strip()
            if not start:
                raise ConfigError("시작 시각을 입력하세요.")
            spec["start"] = start.replace("T", " ")
        else:
            cron = (payload.get("cron") or "").strip()
            if not cron:
                raise ConfigError("반복 주기(cron)를 입력하세요.")
            spec["cron"] = cron

        record = self.store.add(spec)
        return self._job_view(record)


def _name_from_url(url: str) -> str:
    host = (urlparse(url).hostname or "녹화").replace("www.", "")
    return f"{host}-{datetime.now():%m%d-%H%M}"


# ================================================================ HTTP 처리
class Handler(BaseHTTPRequestHandler):
    server_version = "webrec"
    protocol_version = "HTTP/1.1"

    @property
    def app(self) -> WebrecApp:
        return self.server.app  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args) -> None:  # 기본 stderr 출력 대신 로깅
        log.debug("%s - %s", self.address_string(), fmt % args)

    # ------------------------------------------------------------------ 응답
    def _send(self, status: int, body: bytes, content_type: str, extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, data, status: int = 200) -> None:
        self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _error(self, message: str, status: int = 400) -> None:
        self._json({"error": message}, status)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ConfigError(f"잘못된 요청 형식입니다: {exc}") from exc

    # ------------------------------------------------------------------ 라우팅
    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            if path in ("/", "/index.html"):
                return self._static("index.html")
            if path == "/api/state":
                return self._json(self.app.state())
            if path.startswith("/recordings/"):
                return self._download(unquote(path[len("/recordings/"):]))
            if path == "/healthz":
                return self._json({"ok": True})
            return self._error("없는 주소입니다.", HTTPStatus.NOT_FOUND)
        except Exception as exc:
            return self._unexpected(exc)

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            if path == "/api/jobs":
                return self._json(self.app.create_job(self._body()), 201)
            if path.startswith("/api/jobs/"):
                rest = path[len("/api/jobs/"):]
                job_id, _, action = rest.partition("/")
                return self._job_action(job_id, action or "update")
            if path == "/api/settings":
                return self._save_settings(self._body())
            if path == "/api/test-mail":
                return self._test_mail()
            return self._error("없는 주소입니다.", HTTPStatus.NOT_FOUND)
        except ConfigError as exc:
            return self._error(str(exc))
        except WebrecError as exc:
            return self._error(str(exc))
        except Exception as exc:
            return self._unexpected(exc)

    def do_DELETE(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path.startswith("/api/jobs/"):
            job_id = path[len("/api/jobs/"):]
            if self.app.store.delete(job_id):
                return self._json({"ok": True})
            return self._error("없는 예약입니다.", HTTPStatus.NOT_FOUND)
        return self._error("없는 주소입니다.", HTTPStatus.NOT_FOUND)

    # ------------------------------------------------------------------ 동작
    def _job_action(self, job_id: str, action: str) -> None:
        record = self.app.store.get(job_id)
        if record is None:
            return self._error("없는 예약입니다.", HTTPStatus.NOT_FOUND)

        if action == "delete":
            self.app.store.delete(job_id)
            return self._json({"ok": True})
        if action == "check":
            self.app.scheduler.check_now(job_id)
            return self._json({"ok": True, "message": "10초 샘플 점검을 시작했습니다."})
        if action in ("pause", "resume"):
            self.app.store.set_enabled(job_id, action == "resume")
            return self._json({"ok": True})
        return self._error(f"알 수 없는 동작입니다: {action}")

    def _save_settings(self, payload: dict) -> None:
        smtp = payload.get("smtp") or {}
        values: dict = {}
        if smtp:
            current = (self.app.store.settings.get("smtp") or {})
            # 비밀번호 칸이 비어 있으면 기존 값을 유지한다
            if not smtp.get("password"):
                smtp["password"] = current.get("password", "")
            values["smtp"] = smtp
        if payload.get("notify_to"):
            values["notify_to"] = payload["notify_to"]
        self.app.store.update_settings(values)
        return self._json({"ok": True, "mail": self.app.state()["mail"]})

    def _test_mail(self) -> None:
        mailer = self.app.mailer()
        notify = NotifyConfig(to=[self.app.default_recipient()])
        if mailer.dry_run:
            return self._error("메일 설정이 비어 있습니다. SMTP 정보를 먼저 저장하세요.")
        ok = mailer.send_test(notify)
        if not ok:
            return self._error("메일 발송에 실패했습니다. 서버 로그를 확인하세요.")
        return self._json({"ok": True, "message": f"{notify.to[0]} 로 테스트 메일을 보냈습니다."})

    # ------------------------------------------------------------------ 파일
    def _static(self, name: str) -> None:
        path = STATIC_DIR / name
        if not path.is_file():
            return self._error("화면 파일을 찾을 수 없습니다.", HTTPStatus.NOT_FOUND)
        content_type = mimetypes.guess_type(name)[0] or "text/plain"
        if content_type.startswith("text/"):
            content_type += "; charset=utf-8"
        self._send(200, path.read_bytes(), content_type)

    def _download(self, name: str) -> None:
        # 경로 조작 방지: 파일 이름만 허용한다
        safe = Path(name).name
        path = self.app.output_dir / safe
        if not safe or not path.is_file():
            return self._error("파일을 찾을 수 없습니다.", HTTPStatus.NOT_FOUND)
        content_type = mimetypes.guess_type(safe)[0] or "application/octet-stream"
        data = path.read_bytes()
        self._send(200, data, content_type,
                   {"Content-Disposition": _content_disposition(safe)})

    def _unexpected(self, exc: Exception) -> None:
        log.error("요청 처리 중 오류: %s\n%s", exc, traceback.format_exc())
        self._error(f"서버 오류: {exc}", HTTPStatus.INTERNAL_SERVER_ERROR)


def _content_disposition(filename: str) -> str:
    """한글 파일명도 받을 수 있게 만든다.

    HTTP 헤더는 latin-1 만 담을 수 있으므로, 비ASCII 이름은 RFC 5987 방식
    (filename*=UTF-8''...) 으로 내보낸다.
    """
    ascii_name = filename.encode("ascii", "replace").decode("ascii").replace('"', "_")
    quoted = quote(filename, safe="")
    return f"inline; filename=\"{ascii_name}\"; filename*=UTF-8''{quoted}"


class WebrecServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, app: WebrecApp):
        super().__init__(address, Handler)
        self.app = app


def create_server(app: WebrecApp, host: str = "127.0.0.1", port: int = 8765) -> WebrecServer:
    return WebrecServer((host, port), app)


def serve(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    data_dir: Path,
    output_dir: Path,
    log_dir: Path,
) -> int:
    """웹 서버를 띄우고 예약 감시를 시작한다 (Ctrl+C 로 종료)."""
    app = WebrecApp(data_dir=data_dir, output_dir=output_dir, log_dir=log_dir)
    server = create_server(app, host, port)
    app.scheduler.start()

    shown = "127.0.0.1" if host in ("", "0.0.0.0") else host
    log.info("웹 서버 시작: http://%s:%d  (브라우저에서 열어주세요)", shown, port)
    log.info("녹화 저장 폴더: %s", app.output_dir.resolve())
    if host not in ("127.0.0.1", "localhost"):
        log.warning("외부 접속을 허용했습니다(%s). 같은 네트워크의 다른 PC 도 예약을 볼 수 있습니다.", host)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("종료 요청을 받았습니다.")
    finally:
        app.scheduler.stop()
        server.shutdown()
        server.server_close()
    return 0
