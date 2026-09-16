"""소리 녹음 테스트.

'파일에 오디오 트랙이 있다' 와 '실제 소리가 담겼다' 는 다르다.
여기서는 페이지에서 재생한 440Hz 음이 실제로 녹음되는지까지 확인한다.
"""

from __future__ import annotations

import struct
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from conftest import make_video, needs_ffmpeg
from webrec.config import build_config
from webrec.preflight import run_preflight
from webrec.verify import verify_recording


def dominant_frequency(path: Path, *, start: float = 1.0, seconds: float = 2.0) -> tuple[float, float]:
    """녹음된 소리의 주파수와 최대 진폭을 추정한다(영점 통과 방식)."""
    proc = subprocess.run([
        "ffmpeg", "-v", "error", "-i", str(path), "-ss", str(start), "-t", str(seconds),
        "-ac", "1", "-ar", "48000", "-f", "s16le", "-",
    ], capture_output=True)
    raw = proc.stdout
    if len(raw) < 1000:
        return 0.0, 0.0
    samples = struct.unpack(f"<{len(raw) // 2}h", raw[: len(raw) // 2 * 2])
    crossings = sum(1 for i in range(1, len(samples)) if (samples[i - 1] < 0) != (samples[i] < 0))
    duration = len(samples) / 48000
    peak = max(abs(s) for s in samples) / 32768
    return (crossings / 2 / duration if duration else 0.0), peak


# --------------------------------------------------------------- 검증 로직
@needs_ffmpeg
def test_detects_real_sound(tmp_path):
    """소리가 들어 있는 파일은 '무음' 으로 판정하지 않는다."""
    path = make_video(tmp_path / "tone.mp4", seconds=5, silent=False)
    result = verify_recording(path, expected_duration=5, require_audio=True)
    assert result.ok, result.summary()
    assert result.metrics["mean_volume_db"] > -70


@needs_ffmpeg
def test_detects_silence(tmp_path):
    """소리가 필수인데 무음이면 실패로 잡아낸다."""
    path = make_video(tmp_path / "silent.mp4", seconds=5, silent=True)
    result = verify_recording(path, expected_duration=5, require_audio=True)
    assert not result.ok
    assert any("오디오" in check.name for check in result.failures)


@needs_ffmpeg
def test_measures_recorded_tone(tmp_path):
    """440Hz 음을 녹음하면 그대로 440Hz 로 측정된다(측정 방식 자체의 검증)."""
    path = make_video(tmp_path / "tone.mp4", seconds=5, silent=False)
    freq, peak = dominant_frequency(path)
    assert 420 <= freq <= 460, f"주파수가 예상과 다릅니다: {freq}"
    assert peak > 0.05


# ----------------------------------------------- 소리 장치가 없을 때의 처리
def _browser_job(tmp_path, audio=True):
    return build_config({"jobs": [{
        "name": "소리점검", "url": "https://example.com/live", "duration": "10s",
        "backend": "browser", "output_dir": str(tmp_path / "rec"),
        "video": {"resolution": "1280x720", "fps": 15, "audio": audio},
        "preflight": {"duration": 3, "lead_seconds": 0},
    }]}, require_schedule=False).jobs[0]


def test_missing_sound_device_fails_preflight(tmp_path, monkeypatch):
    """소리를 켰는데 녹음 장치가 없으면 사전 점검이 실패로 알려준다."""
    import webrec.preflight as preflight_module

    sample = make_video(tmp_path / "sample.mkv", seconds=3, silent=True)

    class FakeResult:
        path = sample
        attempts = 1
        stderr_tail = ""
        region = None
        notes: list = []
        warnings = [{
            "name": "소리 장치",
            "detail": "소리를 녹음하도록 설정했지만 이 PC 에서 시스템 소리를 받을 장치를 찾지 못했습니다.",
        }]

    monkeypatch.setattr(preflight_module, "capture", lambda *a, **k: FakeResult())
    monkeypatch.setattr(preflight_module, "check_reachable", lambda url, **k: ("ok", "HTTP 200"))

    report = run_preflight(_browser_job(tmp_path))

    assert not report.ok
    assert any(check.name == "소리 장치" for check in report.checks)
    assert "소리" in report.summary()


def test_found_sound_device_is_reported(tmp_path, monkeypatch):
    """장치를 찾으면 점검 결과에 어떤 장치인지 남긴다."""
    import webrec.preflight as preflight_module

    sample = make_video(tmp_path / "sample2.mkv", seconds=3, silent=False)

    class FakeResult:
        path = sample
        attempts = 1
        stderr_tail = ""
        region = None
        notes = ["소리 녹음 장치: 스테레오 믹스(Realtek)"]
        warnings: list = []

    monkeypatch.setattr(preflight_module, "capture", lambda *a, **k: FakeResult())
    monkeypatch.setattr(preflight_module, "check_reachable", lambda url, **k: ("ok", "HTTP 200"))

    report = run_preflight(_browser_job(tmp_path))
    assert report.ok, report.summary()
    assert any("스테레오 믹스" in note for note in report.notes)


@needs_ffmpeg
def test_windows_records_audio_when_device_exists(tmp_path):
    """Windows 명령에 소리 장치가 들어가는지 확인."""
    from webrec.config import VideoConfig
    from webrec.wincapture import build_gdigrab_command

    cmd = build_gdigrab_command(tmp_path / "o.mkv", 60, VideoConfig(audio=True),
                                audio_device="스테레오 믹스(Realtek)")
    assert "dshow" in cmd
    assert "audio=스테레오 믹스(Realtek)" in cmd
    assert cmd[cmd.index("-c:a") + 1] == "aac"
