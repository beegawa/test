"""실제 녹화(캡처) 수행.

두 가지 백엔드:
  stream  - yt-dlp 로 실제 미디어 주소를 얻어 ffmpeg 가 직접 받아 저장 (YouTube/Twitch 등, 화질 최상)
  browser - 가상 화면에 브라우저를 띄우고 화면+소리를 캡처 (Zoom 웹클라이언트 등 로그인/조작이 필요한 곳)

중간에 스트림이 끊기면 남은 시간만큼 자동으로 재시도하고, 조각 파일들을 마지막에 하나로 합친다.
"""

from __future__ import annotations

import logging
import os
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from .errors import CaptureError
from .display import PulseSink, VirtualDisplay
from .sites import BrowserSession, SitePlan, plan_for
from .wincapture import build_gdigrab_command, find_loopback_device, is_windows
from .tools import ffmpeg_path, run, ytdlp_path

log = logging.getLogger(__name__)

_POLL_INTERVAL = 2.0
_MIN_COMPLETE_RATIO = 0.97   # 요청 길이의 97% 이상이면 정상 종료로 본다
_STDERR_TAIL = 4000


@dataclass
class CaptureResult:
    """캡처 1회분 결과."""

    path: Path
    backend: str
    requested_duration: int
    elapsed: float
    attempts: int
    parts: list[Path] = field(default_factory=list)
    stderr_tail: str = ""
    returncode: int = 0
    notes: list[str] = field(default_factory=list)      # 참고 사항
    warnings: list[str] = field(default_factory=list)   # 문제 가능성
    region: tuple[int, int, int, int] | None = None     # 잘라낸 영역

    def to_dict(self) -> dict:
        return {
            "path": str(self.path),
            "backend": self.backend,
            "requested_duration": self.requested_duration,
            "elapsed": round(self.elapsed, 1),
            "attempts": self.attempts,
            "parts": [str(p) for p in self.parts],
            "returncode": self.returncode,
        }


def choose_backend(url: str, requested: str) -> tuple[str, SitePlan]:
    """설정의 backend='auto' 일 때 URL 을 보고 백엔드를 고른다."""
    site = plan_for(url)
    if requested != "auto":
        return requested, site
    backend = site.recommended_backend
    if backend == "stream" and not ytdlp_path():
        log.warning("yt-dlp 가 없어 브라우저 캡처로 대체합니다. (설치 권장: pip install yt-dlp)")
        backend = "browser"
    return backend, site


# --------------------------------------------------------------------- stream
def resolve_stream_urls(url: str, *, timeout: int = 90) -> list[str]:
    """yt-dlp 로 실제 미디어 주소를 얻는다. (영상/음성이 분리되면 2개가 나온다)"""
    lower = url.lower().split("?")[0]
    if lower.endswith((".m3u8", ".mpd", ".mp4", ".ts", ".flv", ".webm")):
        return [url]

    ytdlp = ytdlp_path()
    if not ytdlp:
        raise CaptureError(
            "yt-dlp 가 필요합니다. 설치: pip install -U yt-dlp "
            "(또는 backend: browser 로 지정하세요)"
        )

    cmd = [ytdlp, "-g", "--no-warnings", "--no-playlist", "-f", "bv*+ba/b", url]
    proc = run(cmd, timeout=timeout)
    urls = [line.strip() for line in (proc.stdout or "").splitlines() if line.strip().startswith("http")]
    if proc.returncode != 0 or not urls:
        detail = (proc.stderr or "").strip().splitlines()
        raise CaptureError(
            "라이브 주소를 해석하지 못했습니다(yt-dlp). "
            + (detail[-1][:300] if detail else "방송이 시작되지 않았거나 로그인이 필요한 주소일 수 있습니다.")
        )
    return urls[:2]


def build_stream_command(urls: list[str], out_path: Path, duration: int, video) -> list[str]:
    """ffmpeg 로 스트림을 그대로 저장하는 명령 구성 (재인코딩 없음)."""
    cmd = [ffmpeg_path(), "-hide_banner", "-loglevel", "warning", "-y"]
    for media_url in urls:
        cmd += [
            "-reconnect", "1",
            "-reconnect_streamed", "1",
            "-reconnect_delay_max", "10",
            "-rw_timeout", "15000000",
            "-i", media_url,
        ]
    if len(urls) == 2:
        cmd += ["-map", "0:v:0", "-map", "1:a:0"]
    cmd += ["-t", str(duration), "-c", "copy"]
    if video.container == "mp4":
        cmd += ["-movflags", "+faststart"]
    cmd += [str(out_path)]
    return cmd


# -------------------------------------------------------------------- browser
def build_screen_command(
    display: str,
    audio_source: str | None,
    out_path: Path,
    duration: int,
    video,
    region: tuple[int, int, int, int] | None = None,
) -> list[str]:
    """가상 화면(X11) + 가상 오디오(Pulse)를 캡처하는 ffmpeg 명령.

    region 을 주면 그 영역만 잘라서 녹화한다(영상 부분만 담을 때).
    """
    x, y, width, height = region if region else (0, 0, video.width, video.height)
    cmd = [
        ffmpeg_path(), "-hide_banner", "-loglevel", "warning", "-y",
        "-f", "x11grab",
        "-draw_mouse", "0",
        "-framerate", str(video.fps),
        "-video_size", f"{width}x{height}",
        "-i", f"{display}.0+{x},{y}",
    ]
    if audio_source and video.audio:
        cmd += ["-f", "pulse", "-ac", "2", "-i", audio_source]

    cmd += ["-t", str(duration)]
    if region and (width, height) != (video.width, video.height):
        # 잘라낸 크기가 설정 해상도와 다르면 비율을 지키며 맞춘다
        cmd += ["-vf", f"scale={video.width}:{video.height}:force_original_aspect_ratio=decrease,"
                       f"pad={video.width}:{video.height}:-1:-1:color=black"]
    cmd += [
        "-c:v", video.video_codec,
        "-preset", video.preset,
        "-crf", str(video.crf),
        "-pix_fmt", "yuv420p",
        "-g", str(video.fps * 2),
    ]
    if audio_source and video.audio:
        cmd += ["-c:a", video.audio_codec, "-b:a", "128k"]
    cmd += [str(out_path)]
    return cmd


# ------------------------------------------------------------------ 실행 엔진
def run_ffmpeg(
    cmd: list[str],
    out_path: Path,
    duration: int,
    *,
    stall_timeout: int = 90,
    log_file: Path | None = None,
    env: dict | None = None,
) -> tuple[int, float, str]:
    """ffmpeg 를 돌리며 파일이 실제로 커지는지 감시한다.

    반환: (종료코드, 경과초, stderr 끝부분)
    파일 크기가 stall_timeout 동안 그대로면 끊긴 것으로 보고 중단한다.
    """
    log.debug("ffmpeg: %s", " ".join(cmd))
    started = time.monotonic()
    stderr_chunks: list[str] = []

    handle = open(log_file, "ab") if log_file else None
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            env=env,
        )
    except OSError as exc:
        if handle:
            handle.close()
        raise CaptureError(f"ffmpeg 실행 실패: {exc}") from exc

    last_size = -1
    last_growth = time.monotonic()
    stalled = False

    try:
        while proc.poll() is None:
            time.sleep(_POLL_INTERVAL)
            now = time.monotonic()
            size = out_path.stat().st_size if out_path.exists() else 0
            if size > last_size:
                last_size = size
                last_growth = now
            elif now - last_growth > stall_timeout and now - started > 15:
                log.warning(
                    "%s 초 동안 파일이 커지지 않아 끊긴 것으로 판단합니다 - 재시도합니다.", stall_timeout
                )
                stalled = True
                _stop(proc)
                break
            if now - started > duration + max(120, duration * 0.2):
                log.warning("예상 시간을 크게 넘겨 ffmpeg 를 종료합니다.")
                _stop(proc)
                break
    finally:
        try:
            _, stderr = proc.communicate(timeout=30)
        except subprocess.TimeoutExpired:  # pragma: no cover
            proc.kill()
            _, stderr = proc.communicate()
        if stderr:
            text = stderr.decode("utf-8", errors="replace")
            stderr_chunks.append(text)
            if handle:
                handle.write(stderr)
        if handle:
            handle.close()

    elapsed = time.monotonic() - started
    returncode = proc.returncode if proc.returncode is not None else -1
    if stalled:
        returncode = returncode or 1
    return returncode, elapsed, "".join(stderr_chunks)[-_STDERR_TAIL:]


def recorded_seconds(path: Path) -> float:
    """실제로 저장된 영상 길이(초). 실패하면 0.

    '몇 초 동안 돌았는가(벽시계)' 가 아니라 '몇 초가 저장됐는가' 를 기준으로
    판단해야 이어받기/재시도 계산이 정확하다.
    """
    if not path.exists() or path.stat().st_size == 0:
        return 0.0
    try:
        from .verify import _probe_metrics  # 지연 import (순환 방지)

        return float(_probe_metrics(path).get("duration_sec") or 0.0)
    except Exception:  # pragma: no cover - 손상된 파일
        return 0.0


def _stop(proc: subprocess.Popen) -> None:
    """ffmpeg 가 파일을 정상적으로 마무리하도록 q -> SIGINT -> SIGKILL 순으로 종료."""
    try:
        if proc.stdin and not proc.stdin.closed:
            proc.stdin.write(b"q")
            proc.stdin.flush()
    except (BrokenPipeError, OSError, ValueError):
        pass
    try:
        proc.wait(timeout=10)
        return
    except subprocess.TimeoutExpired:
        pass
    proc.send_signal(signal.SIGINT)
    try:
        proc.wait(timeout=10)
        return
    except subprocess.TimeoutExpired:  # pragma: no cover
        proc.kill()
        proc.wait(timeout=10)


def concat_parts(parts: list[Path], out_path: Path) -> Path:
    """조각 파일들을 재인코딩 없이 하나로 합친다."""
    if len(parts) == 1:
        if parts[0] != out_path:
            shutil.move(str(parts[0]), str(out_path))
        return out_path

    list_file = out_path.with_suffix(out_path.suffix + ".concat.txt")
    list_file.write_text(
        "".join(f"file '{p.resolve().as_posix()}'\n" for p in parts if p.exists()), encoding="utf-8"
    )
    cmd = [
        ffmpeg_path(), "-hide_banner", "-loglevel", "warning", "-y",
        "-f", "concat", "-safe", "0", "-i", str(list_file),
        "-c", "copy", str(out_path),
    ]
    proc = run(cmd, timeout=1800)
    list_file.unlink(missing_ok=True)
    if proc.returncode != 0 or not out_path.exists():
        log.error("조각 합치기 실패 - 조각 파일을 그대로 둡니다: %s", proc.stderr[-500:])
        return parts[0]
    for part in parts:
        part.unlink(missing_ok=True)
    return out_path


def remux_to_mp4(path: Path) -> Path:
    """녹화 후 mp4 로 컨테이너만 바꾼다(재인코딩 없음)."""
    target = path.with_suffix(".mp4")
    cmd = [
        ffmpeg_path(), "-hide_banner", "-loglevel", "warning", "-y",
        "-i", str(path), "-c", "copy", "-movflags", "+faststart", str(target),
    ]
    proc = run(cmd, timeout=3600)
    if proc.returncode != 0 or not target.exists():
        log.warning("mp4 변환 실패 - 원본을 그대로 사용합니다: %s", proc.stderr[-300:])
        return path
    return target


# --------------------------------------------------------------------- 진입점
def capture(
    job,
    out_path: Path,
    duration: int,
    *,
    backend: str | None = None,
    log_file: Path | None = None,
    max_retries: int | None = None,
) -> CaptureResult:
    """job 설정에 따라 duration 초 동안 녹화한다."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    chosen, site = choose_backend(job.url, backend or job.backend)
    retries = job.max_retries if max_retries is None else max_retries

    log.info("녹화 시작 [%s] %s -> %s (%d초)", chosen, job.url, out_path, duration)
    if chosen == "browser":
        return _capture_browser(job, site, out_path, duration, log_file, retries)
    return _capture_stream(job, out_path, duration, log_file, retries)


def _record_loop(
    job,
    out_path: Path,
    duration: int,
    log_file: Path | None,
    retries: int,
    make_cmd,
    *,
    env: dict | None = None,
) -> tuple[list[Path], int, float, str, int]:
    """끊기면 남은 시간만큼 다시 붙는 공통 녹화 루프.

    make_cmd(파일경로, 남은초) -> ffmpeg 명령
    반환: (조각들, 시도횟수, 총경과, stderr 끝부분, 마지막 종료코드)
    """
    parts: list[Path] = []
    attempts = 0
    total_elapsed = 0.0
    stderr_tail = ""
    returncode = 0
    remaining = duration

    while remaining > 2 and attempts <= retries:
        attempts += 1
        part_path = (
            out_path if attempts == 1
            else out_path.with_name(f"{out_path.stem}.part{attempts}{out_path.suffix}")
        )
        cmd = make_cmd(part_path, int(remaining))
        returncode, elapsed, stderr_tail = run_ffmpeg(
            cmd, part_path, int(remaining), stall_timeout=job.stall_timeout,
            log_file=log_file, env=env,
        )
        total_elapsed += elapsed
        captured = recorded_seconds(part_path)
        if captured > 0:
            parts.append(part_path)

        if captured >= remaining * _MIN_COMPLETE_RATIO:
            break

        remaining -= captured
        if remaining > 2 and attempts <= retries:
            log.warning(
                "녹화가 일찍 끝났습니다(%.0f초 남음, 코드 %s). %d초 후 재시도합니다. (%d/%d)",
                remaining, returncode, job.retry_delay, attempts, retries,
            )
            time.sleep(job.retry_delay)

    return parts, attempts, total_elapsed, stderr_tail, returncode


def _finish(
    parts: list[Path], out_path: Path, backend: str, duration: int,
    attempts: int, elapsed: float, stderr_tail: str, returncode: int,
    *, notes: list[str] | None = None, warnings: list[str] | None = None,
    region: tuple[int, int, int, int] | None = None,
) -> CaptureResult:
    if not parts:
        raise CaptureError(
            f"녹화 파일이 만들어지지 않았습니다. ffmpeg 종료코드 {returncode}\n{stderr_tail[-800:]}"
        )
    final = concat_parts(parts, out_path)
    return CaptureResult(
        path=final,
        backend=backend,
        requested_duration=duration,
        elapsed=elapsed,
        attempts=attempts,
        parts=parts if len(parts) > 1 else [],
        stderr_tail=stderr_tail,
        returncode=returncode,
        notes=list(notes or []),
        warnings=list(warnings or []),
        region=region,
    )


def _capture_stream(job, out_path: Path, duration: int, log_file: Path | None, retries: int) -> CaptureResult:
    def make_cmd(part_path: Path, remaining: int) -> list[str]:
        # 재시도할 때마다 주소를 다시 얻는다(라이브 주소는 만료된다)
        return build_stream_command(resolve_stream_urls(job.url), part_path, remaining, job.video)

    parts, attempts, elapsed, stderr_tail, code = _record_loop(
        job, out_path, duration, log_file, retries, make_cmd
    )
    return _finish(parts, out_path, "stream", duration, attempts, elapsed, stderr_tail, code)


def _capture_browser(
    job, site: SitePlan, out_path: Path, duration: int, log_file: Path | None, retries: int
) -> CaptureResult:
    """브라우저를 띄워 화면을 담는다. 운영체제에 따라 방식이 다르다."""
    if is_windows():
        return _capture_browser_windows(job, site, out_path, duration, log_file, retries)
    return _capture_browser_x11(job, site, out_path, duration, log_file, retries)


def _capture_browser_x11(
    job, site: SitePlan, out_path: Path, duration: int, log_file: Path | None, retries: int
) -> CaptureResult:
    """리눅스: 가상 화면(Xvfb)에 브라우저를 띄우고 그 화면만 캡처한다."""
    with VirtualDisplay(job.video.width, job.video.height) as screen, PulseSink() as sink:
        assert screen.display
        env = {**os.environ, "DISPLAY": screen.display}
        with BrowserSession(site, display=screen.display, video=job.video, browser_cfg=job.browser) as browser:
            browser.enter()
            region = browser.capture_region()

            def make_cmd(part_path: Path, remaining: int) -> list[str]:
                return build_screen_command(
                    screen.display, sink.monitor, part_path, remaining, job.video, region
                )

            parts, attempts, elapsed, stderr_tail, code = _record_loop(
                job, out_path, duration, log_file, retries, make_cmd, env=env
            )
            notes, warnings = list(browser.notes), list(browser.warnings)
            if job.video.audio and not sink.monitor:
                warnings.append({
                    "name": "소리 장치",
                    "detail": (
                        "소리를 녹음하도록 설정했지만 소리 장치(PulseAudio)를 쓸 수 없어 "
                        "영상만 녹화됩니다. 설치: sudo apt-get install -y pulseaudio"
                    ),
                })
            elif sink.monitor:
                notes.append(f"소리 녹음 장치: {sink.monitor}")

    return _finish(parts, out_path, "browser", duration, attempts, elapsed, stderr_tail, code,
                   notes=notes, warnings=warnings, region=region)


def _capture_browser_windows(
    job, site: SitePlan, out_path: Path, duration: int, log_file: Path | None, retries: int
) -> CaptureResult:
    """Windows: 실제 화면에 브라우저를 전체화면으로 띄우고 화면을 캡처한다."""
    audio_device = None
    audio_problem: dict | None = None
    if job.video.audio:
        audio_device = find_loopback_device(getattr(job.browser, "audio_device", None))
        if not audio_device:
            audio_problem = {
                "name": "소리 장치",
                "detail": (
                    "소리를 녹음하도록 설정했지만 이 PC 에서 시스템 소리를 받을 장치를 찾지 못했습니다. "
                    "영상만 녹화됩니다. 소리 설정 > 녹음 탭에서 '스테레오 믹스'를 켜거나 "
                    "VB-Audio Virtual Cable 을 설치하세요."
                ),
            }
            log.warning(audio_problem["detail"])

    with BrowserSession(site, display=None, video=job.video, browser_cfg=job.browser) as browser:
        browser.enter()
        region = browser.capture_region()

        def make_cmd(part_path: Path, remaining: int) -> list[str]:
            return build_gdigrab_command(
                part_path, remaining, job.video,
                audio_device=audio_device,
                window_title=getattr(job.browser, "window_title", None),
                offset=(region[0], region[1]) if region else None,
                region=(region[2], region[3]) if region else None,
            )

        parts, attempts, elapsed, stderr_tail, code = _record_loop(
            job, out_path, duration, log_file, retries, make_cmd
        )
        notes, warnings = list(browser.notes), list(browser.warnings)

    if audio_problem:
        warnings.append(audio_problem)
    elif audio_device:
        notes.append(f"소리 녹음 장치: {audio_device}")

    return _finish(parts, out_path, "browser", duration, attempts, elapsed, stderr_tail, code,
                   notes=notes, warnings=warnings, region=region)
