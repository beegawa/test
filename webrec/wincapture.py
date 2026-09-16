"""Windows 전용 화면 캡처.

리눅스는 가상 화면(Xvfb)에 브라우저를 띄워 캡처하지만, Windows 에는 Xvfb 가
없다. 대신 ffmpeg 의 gdigrab 으로 실제 화면을 담고, 소리는 dshow 의
'스테레오 믹스'(루프백) 장치로 받는다.

주의: 실제 화면을 찍으므로 녹화 중에는 화면이 켜져 있어야 하고, 브라우저 창이
가려지면 가린 창이 같이 찍힌다. (README 의 Windows 절 참고)
"""

from __future__ import annotations

import logging
import re
import sys

from .tools import ffmpeg_path, run

log = logging.getLogger(__name__)

# 시스템 소리를 되받을 수 있는(루프백) 장치 이름들. 앞에 있을수록 우선.
LOOPBACK_HINTS = (
    "cable output",          # VB-Audio Virtual Cable
    "voicemeeter out",       # VoiceMeeter
    "스테레오 믹스",
    "stereo mix",
    "stereomix",
    "wave out mix",
    "what u hear",           # Sound Blaster
    "loopback",
)

_DEVICE_RE = re.compile(r'"([^"]+)"\s*\(audio\)', re.IGNORECASE)
_ALT_DEVICE_RE = re.compile(r'\[dshow[^\]]*\]\s+"([^"]+)"')


def is_windows() -> bool:
    return sys.platform.startswith("win")


def list_audio_devices(timeout: int = 20) -> list[str]:
    """ffmpeg 에 잡히는 dshow 오디오 입력 장치 목록."""
    cmd = [ffmpeg_path(), "-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"]
    try:
        proc = run(cmd, timeout=timeout)
    except Exception as exc:  # pragma: no cover - 환경 의존
        log.warning("오디오 장치 목록을 읽지 못했습니다: %s", exc)
        return []

    # ffmpeg 는 이 명령에서 항상 오류로 끝나며, 목록은 stderr 로 나온다.
    text = proc.stderr or ""
    devices = _DEVICE_RE.findall(text)
    if devices:
        return devices

    # ffmpeg 버전에 따라 형식이 다르다: 오디오 구역 안의 따옴표 이름만 모은다
    devices = []
    in_audio_section = False
    for line in text.splitlines():
        lowered = line.lower()
        if "audio devices" in lowered:
            in_audio_section = True
            continue
        if "video devices" in lowered:
            in_audio_section = False
            continue
        if in_audio_section:
            match = _ALT_DEVICE_RE.search(line) or re.search(r'"([^"]+)"', line)
            if match:
                devices.append(match.group(1))
    return devices


def find_loopback_device(preferred: str | None = None) -> str | None:
    """시스템 소리를 녹음할 수 있는 장치를 고른다. 없으면 None."""
    if preferred:
        return preferred
    devices = list_audio_devices()
    if not devices:
        return None
    for hint in LOOPBACK_HINTS:
        for device in devices:
            if hint in device.lower():
                log.info("소리 녹음 장치: %s", device)
                return device
    log.warning(
        "시스템 소리를 녹음할 장치를 찾지 못했습니다. 잡힌 장치: %s\n"
        "  Windows 소리 설정에서 '스테레오 믹스'를 켜거나 VB-Audio Virtual Cable 을 설치하세요.",
        ", ".join(devices[:5]) or "없음",
    )
    return None


def build_gdigrab_command(
    out_path,
    duration: int,
    video,
    *,
    audio_device: str | None = None,
    window_title: str | None = None,
    offset: tuple[int, int] | None = None,
    region: tuple[int, int] | None = None,
):
    """Windows 화면을 녹화하는 ffmpeg 명령.

    window_title 을 주면 그 창만, 없으면 전체 화면을 담는다.
    담은 화면은 설정한 해상도로 맞춰 저장한다.
    """
    cmd = [
        ffmpeg_path(), "-hide_banner", "-loglevel", "warning", "-y",
        "-f", "gdigrab",
        "-draw_mouse", "0",
        "-framerate", str(video.fps),
    ]
    if offset:
        cmd += ["-offset_x", str(offset[0]), "-offset_y", str(offset[1])]
    if region:
        cmd += ["-video_size", f"{region[0]}x{region[1]}"]
    cmd += ["-i", f"title={window_title}" if window_title else "desktop"]

    if audio_device and video.audio:
        cmd += ["-f", "dshow", "-i", f"audio={audio_device}"]

    # 화면 크기가 설정값과 달라도 맞춰서 저장한다(홀수 픽셀은 h264 가 싫어한다)
    cmd += [
        "-t", str(duration),
        "-vf", f"scale={video.width}:{video.height}:force_original_aspect_ratio=decrease,"
               f"pad={video.width}:{video.height}:-1:-1:color=black",
        "-c:v", video.video_codec,
        "-preset", video.preset,
        "-crf", str(video.crf),
        "-pix_fmt", "yuv420p",
        "-g", str(video.fps * 2),
    ]
    if audio_device and video.audio:
        cmd += ["-c:a", video.audio_codec, "-b:a", "128k"]
    cmd += [str(out_path)]
    return cmd
