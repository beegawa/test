"""외부 도구(ffmpeg / ffprobe / yt-dlp / Xvfb / 브라우저) 탐지 및 실행 헬퍼."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path

from .errors import ToolMissingError

log = logging.getLogger(__name__)

_BROWSER_CANDIDATES = (
    os.environ.get("WEBREC_BROWSER", ""),
    "/opt/pw-browsers/chromium",
    "chromium",
    "chromium-browser",
    "google-chrome",
    "google-chrome-stable",
)


def which(name: str) -> str | None:
    return shutil.which(name)


def require(name: str, *, hint: str = "") -> str:
    """필수 도구 경로를 반환하고, 없으면 설치 안내와 함께 오류."""
    path = shutil.which(name)
    if not path:
        message = f"'{name}' 를 찾을 수 없습니다."
        if hint:
            message += f" {hint}"
        raise ToolMissingError(message)
    return path


def ffmpeg_path() -> str:
    return require("ffmpeg", hint="설치: sudo apt-get install -y ffmpeg")


def ffprobe_path() -> str:
    return require("ffprobe", hint="설치: sudo apt-get install -y ffmpeg")


def ytdlp_path() -> str | None:
    """yt-dlp 는 선택 사항(stream 백엔드에서만 필요)."""
    return shutil.which("yt-dlp")


def xvfb_path() -> str | None:
    return shutil.which("Xvfb") or shutil.which("xvfb-run")


def browser_path(explicit: str | None = None) -> str | None:
    """사용 가능한 Chromium 계열 브라우저 경로."""
    candidates = ([explicit] if explicit else []) + list(_BROWSER_CANDIDATES)
    for candidate in candidates:
        if not candidate:
            continue
        if os.path.isabs(candidate):
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
            continue
        found = shutil.which(candidate)
        if found:
            return found
    # Playwright 가 설치한 브라우저 디렉터리 탐색
    for root in (os.environ.get("PLAYWRIGHT_BROWSERS_PATH"), "/opt/pw-browsers"):
        if not root or not Path(root).is_dir():
            continue
        for pattern in ("chromium*/**/chrome", "chromium*/**/headless_shell"):
            for path in sorted(Path(root).glob(pattern)):
                if path.is_file() and os.access(path, os.X_OK):
                    return str(path)
    return None


def run(cmd: list[str], *, timeout: int | None = None, check: bool = False) -> subprocess.CompletedProcess:
    """외부 명령 실행 (stdout/stderr 캡처)."""
    log.debug("실행: %s", " ".join(cmd))
    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        timeout=timeout,
        check=check,
    )


def ffprobe_json(path: str | Path, *, timeout: int = 60) -> dict:
    """ffprobe 로 파일 메타데이터(JSON)를 얻는다."""
    cmd = [
        ffprobe_path(),
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    proc = run(cmd, timeout=timeout)
    if proc.returncode != 0 or not proc.stdout.strip():
        raise ToolMissingError(f"ffprobe 실행 실패: {proc.stderr.strip()[:500]}")
    return json.loads(proc.stdout)


def tool_report() -> dict[str, str | None]:
    """현재 환경에서 사용 가능한 도구 목록 (진단용)."""
    return {
        "ffmpeg": which("ffmpeg"),
        "ffprobe": which("ffprobe"),
        "yt-dlp": ytdlp_path(),
        "Xvfb": xvfb_path(),
        "browser": browser_path(),
        "pulseaudio": which("pulseaudio") or which("pipewire-pulse"),
    }
