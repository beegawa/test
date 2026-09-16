"""녹화 결과 검증 테스트 - 실제 ffmpeg 로 만든 파일을 검사한다."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import make_video, needs_ffmpeg
from webrec.verify import verify_recording


@needs_ffmpeg
def test_good_recording_passes(sample_video: Path):
    result = verify_recording(sample_video, expected_duration=5)
    assert result.ok, result.summary()
    assert result.metrics["has_video"] is True
    assert result.metrics["width"] == 640
    assert result.metrics["black_ratio"] is not None
    assert result.metrics["black_ratio"] < 0.5


@needs_ffmpeg
def test_all_black_recording_is_flagged(black_video: Path):
    """로그인 실패/빈 페이지처럼 화면이 계속 검은 경우를 잡아낸다."""
    result = verify_recording(black_video, expected_duration=5)
    assert not result.ok
    assert any("화면 내용" in c.name for c in result.failures)


@needs_ffmpeg
def test_too_short_recording_is_flagged(tmp_path: Path):
    short = make_video(tmp_path / "short.mp4", seconds=2)
    result = verify_recording(short, expected_duration=10, min_fill_ratio=0.6)
    assert not result.ok
    assert any("녹화 길이" in c.name for c in result.failures)


def test_missing_file_is_flagged(tmp_path: Path):
    result = verify_recording(tmp_path / "없는파일.mkv")
    assert not result.ok
    assert "파일 존재" in result.failures[0].name


def test_empty_file_is_flagged(tmp_path: Path):
    empty = tmp_path / "empty.mkv"
    empty.write_bytes(b"")
    result = verify_recording(empty)
    assert not result.ok
    assert "파일 크기" in result.failures[0].name


def test_garbage_file_is_flagged(tmp_path: Path):
    garbage = tmp_path / "garbage.mkv"
    garbage.write_bytes(b"\x00" * 100_000)
    result = verify_recording(garbage)
    assert not result.ok


@needs_ffmpeg
def test_silent_audio_only_warns_by_default(tmp_path: Path):
    silent = make_video(tmp_path / "silent.mp4", seconds=5, silent=True)
    result = verify_recording(silent, expected_duration=5)
    assert result.ok  # 기본값에서는 무음이어도 통과(경고만)
    assert any("오디오 음량" in w.name for w in result.warnings)


@needs_ffmpeg
def test_silent_audio_fails_when_audio_required(tmp_path: Path):
    silent = make_video(tmp_path / "silent2.mp4", seconds=5, silent=True)
    result = verify_recording(silent, expected_duration=5, require_audio=True)
    assert not result.ok
    assert any("오디오" in c.name for c in result.failures)


@needs_ffmpeg
def test_result_serializes(sample_video: Path):
    data = verify_recording(sample_video, expected_duration=5).to_dict()
    assert data["ok"] is True
    assert isinstance(data["checks"], list)
