"""녹화 결과물 검증.

'파일이 생겼다' 와 '제대로 녹화됐다' 는 다르다. 여기서는 ffprobe/ffmpeg 를 이용해
  1) 비디오 스트림 존재 / 해상도
  2) 실제 길이가 기대치에 근접하는지
  3) 화면이 계속 검정(로그인 실패, 빈 페이지)이 아닌지
  4) 소리가 들어왔는지
를 확인한다. 사전 10초 샘플링과 본 녹화 후 검증 모두 이 모듈을 쓴다.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from .errors import ToolMissingError
from .tools import ffmpeg_path, ffprobe_json, run

log = logging.getLogger(__name__)

# 검사 구간이 이보다 길면 통째로 분석하지 않고 구간 샘플링한다.
_FULL_SCAN_LIMIT = 120
_SCAN_WINDOW = 15

_BLACK_RE = re.compile(r"black_duration:\s*([0-9.]+)")
_MEAN_VOL_RE = re.compile(r"mean_volume:\s*(-?[0-9.]+) dB")
_MAX_VOL_RE = re.compile(r"max_volume:\s*(-?[0-9.]+) dB")


@dataclass
class Check:
    """개별 검사 결과."""

    name: str
    ok: bool
    detail: str
    fatal: bool = True  # False 면 경고로만 취급

    @property
    def symbol(self) -> str:
        return "OK" if self.ok else ("FAIL" if self.fatal else "WARN")


@dataclass
class VerificationResult:
    """검증 종합 결과."""

    path: Path
    checks: list[Check] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks if c.fatal)

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if not c.ok and c.fatal]

    @property
    def warnings(self) -> list[Check]:
        return [c for c in self.checks if not c.ok and not c.fatal]

    def summary(self) -> str:
        lines = [f"{c.symbol:4} | {c.name}: {c.detail}" for c in self.checks]
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "path": str(self.path),
            "ok": self.ok,
            "metrics": self.metrics,
            "checks": [
                {"name": c.name, "ok": c.ok, "detail": c.detail, "fatal": c.fatal} for c in self.checks
            ],
        }


def _probe_metrics(path: Path) -> dict:
    """ffprobe 결과에서 필요한 값만 추출."""
    info = ffprobe_json(path)
    streams = info.get("streams", [])
    fmt = info.get("format", {})

    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

    duration = _to_float(fmt.get("duration"))
    if duration is None and video:
        duration = _to_float(video.get("duration"))

    metrics: dict = {
        "size_bytes": int(fmt.get("size") or path.stat().st_size),
        "duration_sec": duration,
        "format": fmt.get("format_name"),
        "has_video": video is not None,
        "has_audio": audio is not None,
        "bitrate": _to_float(fmt.get("bit_rate")),
    }
    if video:
        metrics.update(
            video_codec=video.get("codec_name"),
            width=video.get("width"),
            height=video.get("height"),
            frames=_to_int(video.get("nb_frames")),
            avg_frame_rate=_fps(video.get("avg_frame_rate")),
        )
    if audio:
        metrics.update(
            audio_codec=audio.get("codec_name"),
            sample_rate=_to_int(audio.get("sample_rate")),
            channels=_to_int(audio.get("channels")),
        )
    return metrics


def _to_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _fps(value) -> float | None:
    if not value or "/" not in str(value):
        return _to_float(value)
    num, _, den = str(value).partition("/")
    try:
        den_f = float(den)
        return float(num) / den_f if den_f else None
    except ValueError:
        return None


def analyze_content(path: Path, *, duration: float | None, want_audio: bool) -> dict:
    """검은 화면 비율 / 음량을 측정한다.

    긴 파일은 앞부분 일부 구간만 검사해서 시간을 아낀다.
    """
    result: dict = {"black_ratio": None, "mean_volume_db": None, "max_volume_db": None}

    scan_len = duration or _SCAN_WINDOW
    seek_args: list[str] = []
    if duration and duration > _FULL_SCAN_LIMIT:
        # 긴 녹화는 중간 구간을 표본으로 검사 (앞부분엔 로딩 화면이 있을 수 있음)
        seek_args = ["-ss", f"{duration / 2:.2f}"]
        scan_len = _SCAN_WINDOW

    filters = ["blackdetect=d=0.2:pic_th=0.98:pix_th=0.10"]
    cmd = [ffmpeg_path(), "-hide_banner", "-nostats"]
    cmd += seek_args + ["-i", str(path), "-t", f"{scan_len:.2f}"]
    if want_audio:
        filters_arg = ["-af", "volumedetect"]
    else:
        filters_arg = []
    cmd += ["-vf", ",".join(filters)] + filters_arg + ["-f", "null", "-"]

    try:
        proc = run(cmd, timeout=max(120, int(scan_len * 4)))
    except (ToolMissingError, OSError) as exc:  # pragma: no cover - 환경 의존
        log.warning("내용 분석 실패: %s", exc)
        return result
    except Exception as exc:  # pragma: no cover
        log.warning("내용 분석 중 예외: %s", exc)
        return result

    stderr = proc.stderr or ""
    black_total = sum(float(m) for m in _BLACK_RE.findall(stderr))
    if scan_len > 0:
        result["black_ratio"] = min(black_total / scan_len, 1.0)

    mean = _MEAN_VOL_RE.search(stderr)
    peak = _MAX_VOL_RE.search(stderr)
    if mean:
        result["mean_volume_db"] = float(mean.group(1))
    if peak:
        result["max_volume_db"] = float(peak.group(1))
    return result


def verify_recording(
    path: str | Path,
    *,
    expected_duration: float | None = None,
    min_fill_ratio: float = 0.6,
    max_black_ratio: float = 0.95,
    require_audio: bool = False,
    min_size_bytes: int = 4 * 1024,
    deep: bool = True,
) -> VerificationResult:
    """녹화 파일이 쓸만한지 검사한다."""
    path = Path(path)
    result = VerificationResult(path=path)

    if not path.exists():
        result.checks.append(Check("파일 존재", False, f"파일이 없습니다: {path}"))
        return result

    size = path.stat().st_size
    result.checks.append(
        Check(
            "파일 크기",
            size >= min_size_bytes,
            f"{size / 1024:.1f} KiB (최소 {min_size_bytes / 1024:.0f} KiB)",
        )
    )
    if size < min_size_bytes:
        result.metrics["size_bytes"] = size
        return result

    try:
        metrics = _probe_metrics(path)
    except Exception as exc:
        result.checks.append(Check("파일 해석(ffprobe)", False, f"읽을 수 없는 파일입니다: {exc}"))
        return result

    result.metrics.update(metrics)
    result.checks.append(
        Check(
            "비디오 스트림",
            bool(metrics.get("has_video")),
            (
                f"{metrics.get('video_codec')} {metrics.get('width')}x{metrics.get('height')}"
                f" @ {metrics.get('avg_frame_rate') or 0:.1f}fps"
                if metrics.get("has_video")
                else "비디오 스트림이 없습니다"
            ),
        )
    )

    duration = metrics.get("duration_sec")
    if expected_duration:
        threshold = expected_duration * min_fill_ratio
        result.checks.append(
            Check(
                "녹화 길이",
                bool(duration and duration >= threshold),
                f"{duration or 0:.1f}s / 기대 {expected_duration:.1f}s (최소 {threshold:.1f}s)",
            )
        )
    else:
        result.checks.append(
            Check("녹화 길이", bool(duration and duration > 0), f"{duration or 0:.1f}s")
        )

    frames = metrics.get("frames")
    if frames is not None:
        result.checks.append(Check("프레임 수", frames > 0, f"{frames} 프레임", fatal=False))

    audio_ok = bool(metrics.get("has_audio"))
    result.checks.append(
        Check(
            "오디오 스트림",
            audio_ok,
            f"{metrics.get('audio_codec')} {metrics.get('channels')}ch" if audio_ok else "오디오 없음",
            fatal=require_audio,
        )
    )

    if deep and metrics.get("has_video"):
        content = analyze_content(path, duration=duration, want_audio=audio_ok)
        result.metrics.update(content)

        black_ratio = content.get("black_ratio")
        if black_ratio is not None:
            result.checks.append(
                Check(
                    "화면 내용",
                    black_ratio < max_black_ratio,
                    f"검은 화면 비율 {black_ratio * 100:.0f}% (허용 {max_black_ratio * 100:.0f}% 미만)",
                )
            )

        mean_db = content.get("mean_volume_db")
        if audio_ok and mean_db is not None:
            silent = mean_db <= -70.0
            result.checks.append(
                Check(
                    "오디오 음량",
                    not silent,
                    f"평균 {mean_db:.1f} dB / 최대 {content.get('max_volume_db')} dB"
                    + (" (무음으로 보입니다)" if silent else ""),
                    fatal=require_audio,
                )
            )

    return result
