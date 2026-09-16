"""명령줄 인터페이스.

  webrec serve     브라우저에서 주소·시간을 입력해 예약하는 웹 화면 실행
  webrec run       설정 파일의 예약을 계속 지켜보며 실행 (상시 실행용)
  webrec once      "시간 + 주소" 만 주고 1회 예약 녹화
  webrec check     10초 샘플로 지금 이 주소가 녹화 가능한지 점검
  webrec verify    이미 녹화된 파일 검증
  webrec list      예약 목록과 다음 실행 시각 확인
  webrec doctor    필요한 프로그램/메일 설정 점검
  webrec test-mail 메일 설정 테스트
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from . import __version__
from .config import (
    Config,
    NotifyConfig,
    build_config,
    format_duration,
    load_config,
    smtp_from_env,
)
from .errors import WebrecError
from .logging_setup import setup_logging
from .notify import Mailer, preflight_body
from .preflight import run_preflight
from .runner import JobRunner
from .schedule import upcoming
from .service import Scheduler
from .tools import tool_report
from .verify import verify_recording

log = logging.getLogger(__name__)

DEFAULT_MAIL = "travislee@shinwon.com"
DEFAULT_CONFIG_NAMES = ("webrec.yaml", "webrec.yml", "config.yaml", "config.yml")


# ------------------------------------------------------------------ 공통 처리
def find_config(explicit: str | None) -> Path | None:
    if explicit:
        return Path(explicit).expanduser()
    for name in DEFAULT_CONFIG_NAMES:
        candidate = Path(name)
        if candidate.is_file():
            return candidate
    return None


def load_or_die(explicit: str | None) -> Config:
    path = find_config(explicit)
    if path is None:
        raise WebrecError(
            "설정 파일을 찾을 수 없습니다. -c 로 경로를 지정하거나 webrec.yaml 을 만드세요. "
            "(config.example.yaml 참고)"
        )
    return load_config(path)


def _ad_hoc_config(args, *, start: str | None) -> Config:
    """설정 파일 없이 명령행 인자만으로 임시 Job 구성."""
    job: dict = {
        "name": args.name,
        "url": args.url,
        "duration": args.duration,
        "backend": args.backend,
        "output_dir": args.out,
        "notify": {"to": args.mail or [DEFAULT_MAIL], "on": list(args.notify_on)},
        "preflight": {
            "enabled": not args.no_preflight,
            "duration": args.sample,
            "lead_seconds": args.lead,
            "abort_on_failure": args.abort_on_preflight_failure,
        },
        "video": {"resolution": args.resolution, "fps": args.fps, "audio": not args.no_audio},
        "remux_mp4": args.mp4,
    }
    if start:
        job["start"] = start
    if getattr(args, "timezone", None):
        job["timezone"] = args.timezone
    if getattr(args, "display_name", None):
        job["browser"] = {"display_name": args.display_name}
    if getattr(args, "passcode", None):
        job.setdefault("browser", {})["passcode"] = args.passcode

    raw = {"jobs": [job], "log_dir": args.log_dir, "state_dir": ".state"}
    config = build_config(raw, require_schedule=False)
    config.smtp = smtp_from_env()
    return config


# ------------------------------------------------------------------- 명령들
def cmd_serve(args) -> int:
    """브라우저에서 예약을 관리하는 웹 서버를 띄운다."""
    from .webserver import serve

    log_dir = Path(args.log_dir).expanduser()
    setup_logging(log_dir, verbose=args.verbose)

    url = f"http://{'127.0.0.1' if args.host in ('', '0.0.0.0') else args.host}:{args.port}"
    print()
    print("=" * 60)
    print("  예약 녹화 웹 화면이 열렸습니다:")
    print(f"    {url}")
    print("  종료하려면 이 창에서 Ctrl+C 를 누르세요.")
    print("=" * 60)
    print()

    if args.open:
        import webbrowser
        import threading

        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    return serve(
        host=args.host,
        port=args.port,
        data_dir=Path(args.data_dir).expanduser(),
        output_dir=Path(args.out).expanduser(),
        log_dir=log_dir,
    )


def cmd_run(args) -> int:
    config = load_or_die(args.config)
    setup_logging(config.log_dir, verbose=args.verbose)
    log.info("webrec %s - 설정 파일: %s", __version__, find_config(args.config))

    mailer = Mailer(config.smtp, dry_run=args.no_mail)
    if mailer.dry_run:
        log.warning("메일 발송이 비활성 상태입니다(SMTP 미설정 또는 --no-mail).")

    scheduler = Scheduler(config, mailer=mailer, dry_run=args.dry_run)
    scheduler.install_signal_handlers()
    return scheduler.run()


def cmd_once(args) -> int:
    config = _ad_hoc_config(args, start=args.at)
    setup_logging(config.log_dir, verbose=args.verbose)
    job = config.jobs[0]

    mailer = Mailer(config.smtp, dry_run=args.no_mail)
    runner = JobRunner(job, mailer, log_dir=config.log_dir)

    scheduled = job.start
    if scheduled is not None:
        tz = job.tzinfo
        if tz is not None:
            scheduled = scheduled.replace(tzinfo=tz)
        now = datetime.now(scheduled.tzinfo) if scheduled.tzinfo else datetime.now()
        if scheduled <= now:
            log.warning("지정한 시각이 이미 지났습니다. 곧바로 녹화를 시작합니다.")
            scheduled = None
        else:
            log.info("예약 시각: %s", scheduled.strftime("%Y-%m-%d %H:%M:%S"))

    outcome = runner.run(scheduled_at=scheduled)
    if args.json:
        print(json.dumps(outcome.to_dict(), ensure_ascii=False, indent=2))
    else:
        print()
        print("결과:", "정상 종료" if outcome.ok else f"실패 ({outcome.stage})")
        if outcome.output_path:
            print("저장 파일:", outcome.output_path)
        if outcome.error:
            print("오류:", outcome.error)
    return 0 if outcome.ok else 1


def cmd_check(args) -> int:
    config = _ad_hoc_config(args, start=None)
    setup_logging(config.log_dir, verbose=args.verbose)
    job = config.jobs[0]

    report = run_preflight(job)
    print()
    print("=" * 60)
    print(f"사전 샘플링 점검 ({report.duration}초)")
    print("=" * 60)
    print(f"대상       : {job.url}")
    print(report.summary())
    print()

    if not args.no_mail:
        mailer = Mailer(config.smtp)
        notify = NotifyConfig(to=list(args.mail) if args.mail else list(job.notify.to))
        subject = f"사전 점검 {'정상' if report.ok else '실패'} - {job.name}"
        mailer.send(notify, subject, preflight_body(job, report))

    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    return 0 if report.ok else 1


def cmd_verify(args) -> int:
    setup_logging(None, verbose=args.verbose)
    result = verify_recording(
        args.path,
        expected_duration=args.expect,
        require_audio=args.require_audio,
    )
    print(result.summary())
    print()
    print("판정:", "정상" if result.ok else "비정상")
    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0 if result.ok else 1


def cmd_list(args) -> int:
    config = load_or_die(args.config)
    setup_logging(None, verbose=args.verbose)

    rows = upcoming(config.jobs)
    if not rows:
        print("예약된 작업이 없습니다.")
        return 0

    print(f"{'작업':<20} {'다음 실행':<22} {'길이':<10} {'방식':<9} 주소")
    print("-" * 100)
    for job, when in rows:
        length = format_duration(job.duration)
        print(f"{job.name:<20} {when.strftime('%Y-%m-%d %H:%M:%S'):<22} {length:<10} {job.backend:<9} {job.url}")

    disabled = [j.name for j in config.jobs if not j.enabled]
    if disabled:
        print("\n비활성화된 작업:", ", ".join(disabled))
    return 0


def cmd_doctor(args) -> int:
    setup_logging(None, verbose=args.verbose)
    print("[외부 프로그램]")
    report = tool_report()
    required = {"ffmpeg", "ffprobe"}
    missing_required = []
    for name, path in report.items():
        mark = "O" if path else "X"
        print(f"  {mark} {name:<12} {path or '없음'}")
        if not path and name in required:
            missing_required.append(name)

    if sys.platform.startswith("win"):
        print("\n[Windows 소리 녹음]")
        from .wincapture import find_loopback_device, list_audio_devices

        device = find_loopback_device()
        if device:
            print(f"  O 소리 장치    {device}")
        else:
            print("  X 소리 장치    시스템 소리를 녹음할 장치가 없습니다.")
            print("     -> 소리 설정 > 녹음 탭에서 '스테레오 믹스' 를 사용으로 바꾸거나,")
            print("        VB-Audio Virtual Cable (무료) 을 설치하세요. 없으면 영상만 녹화됩니다.")
            devices = list_audio_devices()
            if devices:
                print(f"     현재 잡히는 장치: {', '.join(devices[:5])}")

    print("\n[파이썬 패키지]")
    for module, note in (("yaml", "설정 파일 파싱(필수)"), ("playwright", "Zoom 등 브라우저 자동 조작(선택)")):
        try:
            __import__(module)
            print(f"  O {module:<12} {note}")
        except ImportError:
            print(f"  X {module:<12} {note}")

    print("\n[메일 설정]")
    try:
        config = load_or_die(args.config)
        smtp = config.smtp
        source = "설정 파일"
    except WebrecError:
        smtp = smtp_from_env()
        source = "환경변수"
    if smtp.configured:
        print(f"  O SMTP({source}): {smtp.host}:{smtp.port} 발신자={smtp.sender or smtp.username}")
    else:
        print(f"  X SMTP({source}): 미설정 - SMTP_HOST/SMTP_USER/SMTP_PASS 환경변수를 설정하세요.")

    if missing_required:
        print(f"\n필수 프로그램이 없습니다: {', '.join(missing_required)}")
        print("설치: sudo apt-get install -y ffmpeg")
        return 1
    print("\n녹화에 필요한 기본 준비는 끝났습니다.")
    return 0


def cmd_test_mail(args) -> int:
    setup_logging(None, verbose=args.verbose)
    try:
        config = load_or_die(args.config)
        smtp = config.smtp
        default_to = config.jobs[0].notify.to if config.jobs else [DEFAULT_MAIL]
    except WebrecError:
        smtp = smtp_from_env()
        default_to = [DEFAULT_MAIL]

    mailer = Mailer(smtp)
    notify = NotifyConfig(to=list(args.to) if args.to else default_to)
    ok = mailer.send_test(notify)
    print("메일 발송", "성공" if ok else "실패")
    return 0 if ok else 1


# ------------------------------------------------------------------- 파서
def _add_capture_options(parser: argparse.ArgumentParser, *, with_schedule: bool) -> None:
    parser.add_argument("--url", required=True, help="녹화할 라이브 주소 (Zoom/YouTube 등)")
    if with_schedule:
        parser.add_argument("--at", help="시작 시각 'YYYY-MM-DD HH:MM' (생략하면 즉시 시작)")
        parser.add_argument("--duration", default="1h", help="녹화 길이 (예: 90m, 1h30m, 3600)")
    else:
        parser.add_argument("--duration", default="10s", help=argparse.SUPPRESS)
    parser.add_argument("--name", default="adhoc", help="작업 이름 (파일 이름에 사용)")
    parser.add_argument("--backend", default="auto", choices=("auto", "stream", "browser"),
                        help="캡처 방식 (기본 auto: 주소를 보고 자동 선택)")
    parser.add_argument("--out", default="recordings", help="저장 폴더 (기본: recordings)")
    parser.add_argument("--log-dir", default="logs", help="로그 폴더 (기본: logs)")
    parser.add_argument("--resolution", default="1280x720", help="브라우저 캡처 해상도")
    parser.add_argument("--fps", type=int, default=30, help="브라우저 캡처 프레임레이트")
    parser.add_argument("--no-audio", action="store_true", help="소리 없이 녹화")
    parser.add_argument("--mp4", action="store_true", help="녹화 후 mp4 로 변환")
    parser.add_argument("--timezone", help="타임존 (예: Asia/Seoul)")
    parser.add_argument("--display-name", default="Recorder", help="Zoom 등에서 표시할 이름")
    parser.add_argument("--passcode", help="Zoom 회의 암호")
    parser.add_argument("--mail", action="append", help="결과 메일 수신자 (여러 번 지정 가능)")
    parser.add_argument("--no-mail", action="store_true", help="메일을 보내지 않음")
    parser.add_argument("--sample", type=int, default=10, help="사전 점검 샘플 길이(초, 기본 10)")
    parser.add_argument("--lead", type=int, default=300, help="시작 몇 초 전에 점검할지 (기본 300)")
    parser.add_argument("--no-preflight", action="store_true", help="사전 점검 생략")
    parser.add_argument("--abort-on-preflight-failure", action="store_true",
                        help="사전 점검 실패 시 녹화를 취소")
    parser.add_argument("--notify-on", action="append",
                        default=None, help="알림 이벤트 (preflight_failed/started/completed/failed)")
    parser.add_argument("--json", action="store_true", help="결과를 JSON 으로 출력")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="webrec",
        description="정해진 시간에 Zoom/YouTube 등 웹 라이브를 녹화·저장하고 결과를 메일로 알립니다.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "예시:\n"
            "  webrec check --url https://youtube.com/watch?v=xxxx\n"
            "  webrec once  --url https://zoom.us/j/123456?pwd=abc --at '2026-09-20 21:00' --duration 1h30m\n"
            "  webrec run   -c webrec.yaml\n"
            "  webrec serve --open        # 브라우저에서 예약하기\n"
        ),
    )
    parser.add_argument("--version", action="version", version=f"webrec {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="자세한 로그 출력")
    sub = parser.add_subparsers(dest="command", required=True)

    p_serve = sub.add_parser("serve", help="브라우저에서 예약하는 웹 화면 실행")
    p_serve.add_argument("--host", default="127.0.0.1",
                         help="접속 허용 주소 (기본 127.0.0.1 = 내 PC 에서만)")
    p_serve.add_argument("--port", type=int, default=8765, help="포트 (기본 8765)")
    p_serve.add_argument("--data-dir", default=".webrec", help="예약 목록 저장 폴더")
    p_serve.add_argument("--out", default="recordings", help="녹화 저장 폴더")
    p_serve.add_argument("--log-dir", default="logs", help="로그 폴더")
    p_serve.add_argument("--open", action="store_true", help="브라우저를 자동으로 연다")
    p_serve.set_defaults(func=cmd_serve)

    p_run = sub.add_parser("run", help="설정 파일의 예약을 계속 실행 (상시 실행)")
    p_run.add_argument("-c", "--config", help="설정 파일 경로")
    p_run.add_argument("--no-mail", action="store_true", help="메일을 보내지 않음")
    p_run.add_argument("--dry-run", action="store_true", help="예약만 확인하고 실제 녹화는 하지 않음")
    p_run.set_defaults(func=cmd_run)

    p_once = sub.add_parser("once", help="시간과 주소만 주고 1회 예약 녹화")
    _add_capture_options(p_once, with_schedule=True)
    p_once.set_defaults(func=cmd_once)

    p_check = sub.add_parser("check", help="10초 샘플로 녹화 가능 여부 점검")
    _add_capture_options(p_check, with_schedule=False)
    p_check.set_defaults(func=cmd_check)

    p_verify = sub.add_parser("verify", help="이미 녹화된 파일 검증")
    p_verify.add_argument("path", help="검증할 파일 경로")
    p_verify.add_argument("--expect", type=float, help="기대 길이(초)")
    p_verify.add_argument("--require-audio", action="store_true", help="오디오가 없으면 실패로 처리")
    p_verify.add_argument("--json", action="store_true", help="결과를 JSON 으로 출력")
    p_verify.set_defaults(func=cmd_verify)

    p_list = sub.add_parser("list", help="예약 목록과 다음 실행 시각")
    p_list.add_argument("-c", "--config", help="설정 파일 경로")
    p_list.set_defaults(func=cmd_list)

    p_doctor = sub.add_parser("doctor", help="필요한 프로그램/메일 설정 점검")
    p_doctor.add_argument("-c", "--config", help="설정 파일 경로")
    p_doctor.set_defaults(func=cmd_doctor)

    p_mail = sub.add_parser("test-mail", help="메일 설정 테스트")
    p_mail.add_argument("-c", "--config", help="설정 파일 경로")
    p_mail.add_argument("--to", action="append", help="수신자 (기본: 설정 파일 값)")
    p_mail.set_defaults(func=cmd_test_mail)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if getattr(args, "notify_on", None) is None and hasattr(args, "notify_on"):
        args.notify_on = ["preflight_failed", "started", "completed", "failed"]

    try:
        return args.func(args)
    except WebrecError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:  # pragma: no cover
        print("\n중단했습니다.", file=sys.stderr)
        return 130


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
