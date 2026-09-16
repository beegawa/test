"""설정 파일(YAML/JSON) 로딩 및 검증.

사용자는 "시간 + 라이브 주소"만 적으면 되고, 나머지는 defaults 로 채워진다.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any

try:  # Python 3.9+
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover - 3.8 이하
    ZoneInfo = None  # type: ignore[assignment]
    ZoneInfoNotFoundError = Exception  # type: ignore[misc,assignment]

from .errors import ConfigError

# 알림 이벤트 종류
NOTIFY_EVENTS = (
    "preflight_passed",   # 사전 샘플링 성공
    "preflight_failed",   # 사전 샘플링 실패
    "started",            # 본 녹화 시작
    "completed",          # 정상 종료
    "failed",             # 비정상 종료
)

DEFAULT_NOTIFY_EVENTS = ("preflight_failed", "completed", "failed")

BACKENDS = ("auto", "stream", "browser")

_DURATION_RE = re.compile(
    r"^\s*(?:(?P<h>\d+(?:\.\d+)?)\s*h)?"
    r"\s*(?:(?P<m>\d+(?:\.\d+)?)\s*m)?"
    r"\s*(?:(?P<s>\d+(?:\.\d+)?)\s*s)?\s*$",
    re.IGNORECASE,
)

_ENV_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")

_DATETIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
)


def parse_duration(value: Any, *, field_name: str = "duration", allow_zero: bool = False) -> int:
    """'1h30m', '90m', '5400', 5400 -> 초(int).

    allow_zero=True 이면 0 을 허용한다(예: 사전 점검 리드타임 0 = 점검 직후 바로 시작).
    """
    if isinstance(value, bool):
        raise ConfigError(f"{field_name}: 숫자 또는 '1h30m' 형식의 문자열이어야 합니다.")
    if isinstance(value, (int, float)):
        seconds = float(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise ConfigError(f"{field_name}: 값이 비어 있습니다.")
        if re.fullmatch(r"\d+(\.\d+)?", text):
            seconds = float(text)
        else:
            match = _DURATION_RE.match(text)
            if not match or not any(match.groupdict().values()):
                raise ConfigError(
                    f"{field_name}: '{value}' 를 해석할 수 없습니다. 예) 3600, '90m', '1h30m'"
                )
            seconds = (
                float(match.group("h") or 0) * 3600
                + float(match.group("m") or 0) * 60
                + float(match.group("s") or 0)
            )
    else:
        raise ConfigError(f"{field_name}: 숫자 또는 문자열이어야 합니다 (받은 값: {value!r}).")

    if seconds < 0 or (seconds == 0 and not allow_zero):
        raise ConfigError(f"{field_name}: 0보다 커야 합니다 (받은 값: {value!r}).")
    return int(round(seconds))


def format_duration(seconds: int | float) -> str:
    """초 -> '1시간 30분', '40분', '30초' 처럼 읽기 좋은 문자열."""
    seconds = int(round(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    parts = []
    if hours:
        parts.append(f"{hours}시간")
    if minutes:
        parts.append(f"{minutes}분")
    if secs and not hours:
        parts.append(f"{secs}초")
    return " ".join(parts) or "0초"


def parse_datetime(value: Any, *, field_name: str = "start") -> datetime:
    """'2026-09-20 21:00' 같은 로컬 시각 문자열 -> naive datetime."""
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    if not isinstance(value, str):
        raise ConfigError(f"{field_name}: 'YYYY-MM-DD HH:MM' 형식의 문자열이어야 합니다.")
    text = value.strip()
    for fmt in _DATETIME_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ConfigError(
            f"{field_name}: '{value}' 를 해석할 수 없습니다. 예) '2026-09-20 21:00'"
        ) from exc
    return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed


def resolve_timezone(name: str | None):
    """타임존 이름 -> tzinfo. None 이면 시스템 로컬 타임존(None) 사용."""
    if not name:
        return None
    if ZoneInfo is None:  # pragma: no cover
        raise ConfigError("이 파이썬 버전에서는 timezone 설정을 사용할 수 없습니다 (zoneinfo 없음).")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ConfigError(f"timezone: 알 수 없는 타임존 '{name}'") from exc


def expand_env(value: Any) -> Any:
    """설정값 안의 ${VAR} / ${VAR:-기본값} 을 환경변수로 치환."""
    if isinstance(value, str):
        def _sub(match: re.Match[str]) -> str:
            name, default = match.group(1), match.group(2)
            return os.environ.get(name, default if default is not None else "")

        return _ENV_RE.sub(_sub, value)
    if isinstance(value, dict):
        return {k: expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [expand_env(v) for v in value]
    return value


@dataclass
class PreflightConfig:
    """본 녹화 전 10초 샘플링 점검 설정."""

    enabled: bool = True
    duration: int = 10            # 샘플 길이(초)
    lead_seconds: int = 300       # 시작 몇 초 전에 점검할지
    abort_on_failure: bool = False  # 실패 시 본 녹화를 포기할지
    keep_sample: bool = False     # 샘플 파일을 남길지
    min_fill_ratio: float = 0.6   # 샘플 길이 대비 실제 녹화 길이 최소 비율
    max_black_ratio: float = 0.95  # 검은 화면 허용 비율
    require_audio: bool = False   # 오디오가 없으면 실패로 볼지


@dataclass
class VideoConfig:
    """캡처 품질 설정 (browser 백엔드에서 주로 사용)."""

    resolution: str = "1280x720"
    fps: int = 30
    audio: bool = True
    video_codec: str = "libx264"
    audio_codec: str = "aac"
    preset: str = "veryfast"
    crf: int = 23
    container: str = "mkv"  # mkv 는 중간에 죽어도 파일이 살아남는다

    @property
    def width(self) -> int:
        return int(self.resolution.lower().split("x")[0])

    @property
    def height(self) -> int:
        return int(self.resolution.lower().split("x")[1])


@dataclass
class BrowserConfig:
    """브라우저 캡처 백엔드 옵션."""

    display_name: str = "Recorder"    # Zoom 등에서 사용할 표시 이름
    email: str | None = None          # Zoom 웨비나 입장 시 요구하는 이메일
    passcode: str | None = None
    page_load_wait: int = 20          # 페이지 로딩 후 대기(초)
    executable_path: str | None = None
    mute_page: bool = False
    audio_device: str | None = None   # Windows: 소리를 받을 dshow 장치 이름
    window_title: str | None = None   # Windows: 이 제목의 창만 캡처
    capture: str = "auto"             # auto | video | screen | region - 아래 설명 참고
    region: str | None = None         # capture=region 일 때 "x,y,너비,높이"
    extra_args: list[str] = field(default_factory=list)


@dataclass
class NotifyConfig:
    """메일 알림 설정."""

    to: list[str] = field(default_factory=lambda: ["travislee@shinwon.com"])
    events: list[str] = field(default_factory=lambda: list(DEFAULT_NOTIFY_EVENTS))
    attach_log: bool = True
    subject_prefix: str = "[webrec]"


@dataclass
class SmtpConfig:
    """SMTP 서버 설정 (비밀번호는 환경변수 사용 권장)."""

    host: str = ""
    port: int = 587
    username: str = ""
    password: str = ""
    sender: str = ""
    starttls: bool = True
    ssl: bool = False
    timeout: int = 30

    @property
    def configured(self) -> bool:
        return bool(self.host)


@dataclass
class Job:
    """녹화 작업 하나."""

    name: str
    url: str
    duration: int
    start: datetime | None = None          # 1회성 예약 시각
    cron: str | None = None                # 반복 예약 (5-field cron)
    timezone: str | None = None
    backend: str = "auto"
    output_dir: Path = Path("recordings")
    enabled: bool = True
    max_retries: int = 3                   # 녹화 중 끊겼을 때 재시도 횟수
    retry_delay: int = 5
    stall_timeout: int = 90                # 파일이 이 시간 동안 안 커지면 끊긴 것으로 간주
    remux_mp4: bool = False                # 종료 후 mp4 로 변환할지
    preflight: PreflightConfig = field(default_factory=PreflightConfig)
    video: VideoConfig = field(default_factory=VideoConfig)
    browser: BrowserConfig = field(default_factory=BrowserConfig)
    notify: NotifyConfig = field(default_factory=NotifyConfig)

    @property
    def tzinfo(self):
        return resolve_timezone(self.timezone)


@dataclass
class Config:
    """전체 설정."""

    jobs: list[Job] = field(default_factory=list)
    smtp: SmtpConfig = field(default_factory=SmtpConfig)
    log_dir: Path = Path("logs")
    state_dir: Path = Path(".state")

    def job(self, name: str) -> Job:
        for job in self.jobs:
            if job.name == name:
                return job
        raise ConfigError(f"'{name}' 이라는 이름의 작업을 찾을 수 없습니다.")


def _as_dict(value: Any, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"{field_name}: 딕셔너리(맵) 형태여야 합니다.")
    return value


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """중첩 딕셔너리 병합 (override 우선)."""
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _build_dataclass(cls, data: dict[str, Any], field_name: str, aliases: dict[str, str] | None = None):
    aliases = aliases or {}
    known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
    kwargs: dict[str, Any] = {}
    for key, value in data.items():
        target = aliases.get(key, key)
        if target not in known:
            raise ConfigError(f"{field_name}: 알 수 없는 항목 '{key}' (사용 가능: {sorted(known)})")
        kwargs[target] = value
    return cls(**kwargs)


def _build_preflight(data: dict[str, Any]) -> PreflightConfig:
    data = dict(data)
    if "duration" in data:
        data["duration"] = parse_duration(data["duration"], field_name="preflight.duration")
    if "lead_seconds" in data:
        data["lead_seconds"] = parse_duration(
            data["lead_seconds"], field_name="preflight.lead_seconds", allow_zero=True
        )
    cfg = _build_dataclass(PreflightConfig, data, "preflight", {"lead": "lead_seconds"})
    if cfg.duration < 3:
        raise ConfigError("preflight.duration: 최소 3초 이상이어야 합니다 (권장 10초).")
    return cfg


def _build_notify(data: dict[str, Any]) -> NotifyConfig:
    data = dict(data)
    # YAML 1.1 에서 'on:' 은 불리언 True 로 읽힌다. 둘 다 events 로 받아준다.
    for key in ("on", True):
        if key in data:
            data["events"] = data.pop(key)
    to = data.get("to")
    if isinstance(to, str):
        data["to"] = [addr.strip() for addr in to.split(",") if addr.strip()]
    events = data.get("events")
    if isinstance(events, str):
        data["events"] = [e.strip() for e in events.split(",") if e.strip()]
    cfg = _build_dataclass(NotifyConfig, data, "notify")
    for event in cfg.events:
        if event not in NOTIFY_EVENTS:
            raise ConfigError(f"notify.on: 알 수 없는 이벤트 '{event}' (사용 가능: {list(NOTIFY_EVENTS)})")
    if not cfg.to:
        raise ConfigError("notify.to: 수신자 메일 주소가 최소 하나 필요합니다.")
    return cfg


CAPTURE_MODES = ("auto", "video", "screen", "region")


def _build_browser(data: dict[str, Any], job_name: str) -> BrowserConfig:
    cfg = _build_dataclass(BrowserConfig, data, f"'{job_name}'.browser")
    mode = (cfg.capture or "auto").lower()
    if mode not in CAPTURE_MODES:
        raise ConfigError(
            f"'{job_name}'.browser.capture: {list(CAPTURE_MODES)} 중 하나여야 합니다 (받은 값: {cfg.capture})"
        )
    if mode == "region" and not cfg.region:
        raise ConfigError(f"'{job_name}'.browser.capture=region 이면 region 에 'x,y,너비,높이' 가 필요합니다.")
    return replace(cfg, capture=mode)


def _build_video(data: dict[str, Any]) -> VideoConfig:
    cfg = _build_dataclass(VideoConfig, data, "video")
    if not re.fullmatch(r"\d+x\d+", cfg.resolution.lower()):
        raise ConfigError(f"video.resolution: 'WIDTHxHEIGHT' 형식이어야 합니다 (받은 값: {cfg.resolution}).")
    if cfg.fps <= 0:
        raise ConfigError("video.fps: 0보다 커야 합니다.")
    return cfg


def _build_smtp(data: dict[str, Any]) -> SmtpConfig:
    data = dict(data)
    if "from" in data:
        data["sender"] = data.pop("from")
    cfg = _build_dataclass(SmtpConfig, data, "smtp", {"user": "username", "tls": "starttls"})
    if cfg.configured and not cfg.sender:
        cfg = replace(cfg, sender=cfg.username)
    return cfg


def _build_job(
    raw: dict[str, Any], defaults: dict[str, Any], index: int, *, require_schedule: bool = True
) -> Job:
    merged = _merge(defaults, raw)

    name = merged.get("name") or f"job{index + 1}"
    if not isinstance(name, str):
        raise ConfigError(f"jobs[{index}].name: 문자열이어야 합니다.")

    url = merged.get("url")
    if not url or not isinstance(url, str):
        raise ConfigError(f"'{name}': url 은 반드시 필요합니다 (녹화할 라이브 주소).")
    if not re.match(r"^https?://", url.strip(), re.IGNORECASE):
        raise ConfigError(f"'{name}': url 은 http:// 또는 https:// 로 시작해야 합니다 (받은 값: {url}).")

    if "duration" not in merged:
        raise ConfigError(f"'{name}': duration 은 반드시 필요합니다 (예: '1h30m').")
    duration = parse_duration(merged["duration"], field_name=f"'{name}'.duration")

    start = parse_datetime(merged["start"], field_name=f"'{name}'.start") if merged.get("start") else None
    cron = merged.get("cron")
    if start is None and not cron and require_schedule:
        raise ConfigError(f"'{name}': start (1회 예약) 또는 cron (반복 예약) 중 하나가 필요합니다.")
    if start is not None and cron:
        raise ConfigError(f"'{name}': start 와 cron 은 동시에 쓸 수 없습니다.")

    backend = str(merged.get("backend", "auto")).lower()
    if backend not in BACKENDS:
        raise ConfigError(f"'{name}': backend 는 {list(BACKENDS)} 중 하나여야 합니다 (받은 값: {backend}).")

    timezone = merged.get("timezone")
    resolve_timezone(timezone)  # 이름 검증

    job = Job(
        name=name,
        url=url.strip(),
        duration=duration,
        start=start,
        cron=str(cron) if cron else None,
        timezone=timezone,
        backend=backend,
        output_dir=Path(str(merged.get("output_dir", "recordings"))).expanduser(),
        enabled=bool(merged.get("enabled", True)),
        max_retries=int(merged.get("max_retries", 3)),
        retry_delay=int(merged.get("retry_delay", 5)),
        stall_timeout=int(merged.get("stall_timeout", 90)),
        remux_mp4=bool(merged.get("remux_mp4", False)),
        preflight=_build_preflight(_as_dict(merged.get("preflight"), f"'{name}'.preflight")),
        video=_build_video(_as_dict(merged.get("video"), f"'{name}'.video")),
        browser=_build_browser(_as_dict(merged.get("browser"), f"'{name}'.browser"), name),
        notify=_build_notify(_as_dict(merged.get("notify"), f"'{name}'.notify")),
    )

    if job.cron:
        from .schedule import validate_cron  # 순환 import 방지를 위해 지연 import

        validate_cron(job.cron, field_name=f"'{name}'.cron")
    return job


def load_config(path: str | Path) -> Config:
    """YAML 또는 JSON 설정 파일을 읽어 Config 로 만든다."""
    path = Path(path).expanduser()
    if not path.is_file():
        raise ConfigError(f"설정 파일을 찾을 수 없습니다: {path}")

    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        raw = json.loads(text)
    else:
        import yaml

        raw = yaml.safe_load(text)

    if not isinstance(raw, dict):
        raise ConfigError("설정 파일 최상위는 딕셔너리(맵)여야 합니다.")

    raw = expand_env(raw)
    return build_config(raw)


def build_config(raw: dict[str, Any], *, require_schedule: bool = True) -> Config:
    """이미 파싱된 딕셔너리로부터 Config 생성.

    require_schedule=False 는 명령행에서 즉시 실행할 때처럼 예약 시각이 없는 경우에 쓴다.
    """
    defaults = _as_dict(raw.get("defaults"), "defaults")
    jobs_raw = raw.get("jobs") or []
    if not isinstance(jobs_raw, list):
        raise ConfigError("jobs: 리스트여야 합니다.")

    jobs = [
        _build_job(_as_dict(item, f"jobs[{i}]"), defaults, i, require_schedule=require_schedule)
        for i, item in enumerate(jobs_raw)
    ]

    names = [job.name for job in jobs]
    duplicates = {n for n in names if names.count(n) > 1}
    if duplicates:
        raise ConfigError(f"작업 이름이 중복되었습니다: {sorted(duplicates)}")

    return Config(
        jobs=jobs,
        smtp=_build_smtp(_as_dict(raw.get("smtp"), "smtp")),
        log_dir=Path(str(raw.get("log_dir", "logs"))).expanduser(),
        state_dir=Path(str(raw.get("state_dir", ".state"))).expanduser(),
    )


def smtp_from_env() -> SmtpConfig:
    """설정 파일 없이 환경변수만으로 SMTP 구성 (once/check 명령용)."""
    return SmtpConfig(
        host=os.environ.get("SMTP_HOST", ""),
        port=int(os.environ.get("SMTP_PORT", "587")),
        username=os.environ.get("SMTP_USER", ""),
        password=os.environ.get("SMTP_PASS", ""),
        sender=os.environ.get("SMTP_FROM", os.environ.get("SMTP_USER", "")),
        starttls=os.environ.get("SMTP_STARTTLS", "1") not in ("0", "false", "False"),
        ssl=os.environ.get("SMTP_SSL", "0") in ("1", "true", "True"),
    )
