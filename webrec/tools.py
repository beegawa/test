"""외부 도구(ffmpeg / ffprobe / yt-dlp / Xvfb / 브라우저) 탐지 및 실행 헬퍼."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
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
    # Windows 기본 설치 경로 (Chrome -> Edge 순)
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "chrome",
    "msedge",
)


# 프로그램이 설치된 폴더 (여기 tools/ffmpeg 에 직접 받아둘 수도 있다)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _windows_candidates(name: str) -> list[str]:
    """PATH 에 없어도 흔히 설치되는 Windows 위치들을 훑는다.

    Windows 에서 'ffmpeg 는 깔았는데 PATH 에 안 잡힌다' 가 워낙 흔해서,
    자동으로 찾아준다.
    """
    exe = f"{name}.exe"
    local = os.environ.get("LOCALAPPDATA", "")
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    program_data = os.environ.get("ProgramData", r"C:\ProgramData")
    user = os.environ.get("USERPROFILE", "")

    fixed = [
        _PROJECT_ROOT / "tools" / "ffmpeg" / "bin" / exe,       # 설치 스크립트가 받아둔 것
        Path(program_files) / "ffmpeg" / "bin" / exe,
        Path(r"C:\ffmpeg\bin") / exe,
        Path(program_data) / "chocolatey" / "bin" / exe,
    ]
    if local:
        fixed += [Path(local) / "Microsoft" / "WinGet" / "Links" / exe]
    if user:
        fixed += [Path(user) / "scoop" / "shims" / exe]

    found = [str(path) for path in fixed if path.is_file()]

    # winget 은 버전별 폴더에 풀어놓는다: .../WinGet/Packages/Gyan.FFmpeg.../bin/ffmpeg.exe
    globs = [_PROJECT_ROOT / "tools"]
    if local:
        globs.append(Path(local) / "Microsoft" / "WinGet" / "Packages")
    for base in globs:
        if not base.is_dir():
            continue
        for path in sorted(base.glob(f"**/{exe}"))[:5]:
            found.append(str(path))
    return found


def find_tool(name: str) -> str | None:
    """실행 파일을 찾는다. PATH 를 먼저 보고, Windows 는 흔한 설치 위치도 본다."""
    override = os.environ.get(f"WEBREC_{name.upper()}")
    if override:
        candidate = Path(override)
        if candidate.is_dir():           # 폴더를 줬으면 그 안에서 찾는다
            for exe in (name, f"{name}.exe"):
                if (candidate / exe).is_file():
                    return str(candidate / exe)
        elif candidate.is_file():
            return str(candidate)

    path = shutil.which(name)
    if path:
        return path
    if sys.platform.startswith("win"):
        for found in _windows_candidates(name):
            return found
    return None


def which(name: str) -> str | None:
    return find_tool(name)


def require(name: str, *, hint: str = "") -> str:
    """필수 도구 경로를 반환하고, 없으면 설치 안내와 함께 오류."""
    path = find_tool(name)
    if not path:
        message = f"'{name}' 를 찾을 수 없습니다."
        if hint:
            message += f" {hint}"
        raise ToolMissingError(message)
    return path


_FFMPEG_HINT = (
    "설치: Windows 는 '예약녹화-시작.bat' 을 실행하면 자동으로 설치됩니다. "
    "리눅스는 sudo apt-get install -y ffmpeg"
)


def ffmpeg_path() -> str:
    return require("ffmpeg", hint=_FFMPEG_HINT)


def ffprobe_path() -> str:
    return require("ffprobe", hint=_FFMPEG_HINT)


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
    """현재 환경에서 사용 가능한 도구 목록 (진단용).

    운영체제마다 필요한 것이 다르므로 해당 OS 에서 쓰는 것만 보여준다.
    (자주 호출되므로 여기서는 빠른 확인만 한다)
    """
    report: dict[str, str | None] = {
        "ffmpeg": which("ffmpeg"),
        "ffprobe": which("ffprobe"),
        "yt-dlp": ytdlp_path(),
        "browser": browser_path(),
    }
    if sys.platform.startswith("win"):
        return report
    report["Xvfb"] = xvfb_path()
    report["pulseaudio"] = which("pulseaudio") or which("pipewire-pulse")
    return report
