"""캡처 명령 구성/백엔드 선택/사이트 판별 테스트."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import make_video, needs_ffmpeg
from webrec.capture import (
    build_screen_command,
    build_stream_command,
    choose_backend,
    concat_parts,
    resolve_stream_urls,
)
from webrec.config import VideoConfig, build_config
from webrec.errors import CaptureError
from webrec.sites import plan_for, zoom_web_client_url


def _job(url: str, backend: str = "auto"):
    return build_config({"jobs": [{
        "name": "t", "url": url, "duration": "10m", "start": "2030-01-01 10:00", "backend": backend,
    }]}).jobs[0]


# --------------------------------------------------------------- 사이트 판별
@pytest.mark.parametrize("url,kind", [
    ("https://zoom.us/j/1234567890?pwd=abc", "zoom"),
    ("https://company.zoom.us/j/999", "zoom"),
    ("https://www.youtube.com/watch?v=abc", "stream"),
    ("https://youtu.be/abc", "stream"),
    ("https://www.twitch.tv/someone", "stream"),
    ("https://cdn.example.com/live/stream.m3u8", "stream"),
    ("https://intranet.example.com/webinar", "generic"),
])
def test_plan_for(url, kind):
    assert plan_for(url).kind == kind


def test_zoom_url_is_converted_to_web_client():
    assert zoom_web_client_url("https://zoom.us/j/1234567890?pwd=abc") == \
        "https://zoom.us/wc/join/1234567890?pwd=abc"
    assert zoom_web_client_url("https://company.zoom.us/j/999") == \
        "https://company.zoom.us/wc/join/999"
    # 이미 웹 클라이언트 주소면 그대로
    assert zoom_web_client_url("https://zoom.us/wc/join/999") == "https://zoom.us/wc/join/999"


def test_zoom_always_uses_browser_backend():
    backend, plan = choose_backend("https://zoom.us/j/123", "auto")
    assert backend == "browser"
    assert plan.kind == "zoom"


def test_explicit_backend_is_respected():
    backend, _ = choose_backend("https://zoom.us/j/123", "stream")
    assert backend == "stream"


def test_youtube_prefers_stream_when_ytdlp_available(monkeypatch):
    monkeypatch.setattr("webrec.capture.ytdlp_path", lambda: "/usr/bin/yt-dlp")
    backend, _ = choose_backend("https://www.youtube.com/watch?v=abc", "auto")
    assert backend == "stream"


def test_falls_back_to_browser_without_ytdlp(monkeypatch):
    monkeypatch.setattr("webrec.capture.ytdlp_path", lambda: None)
    backend, _ = choose_backend("https://www.youtube.com/watch?v=abc", "auto")
    assert backend == "browser"


# ------------------------------------------------------------- 명령어 구성
def test_stream_command_copies_without_reencoding(tmp_path):
    cmd = build_stream_command(["https://cdn/live.m3u8"], tmp_path / "out.mkv", 600, VideoConfig())
    assert "-c" in cmd and cmd[cmd.index("-c") + 1] == "copy"
    assert cmd[cmd.index("-t") + 1] == "600"
    assert "-reconnect" in cmd  # 끊김 대비 재접속 옵션


def test_stream_command_maps_separate_video_and_audio(tmp_path):
    cmd = build_stream_command(["https://cdn/v.m4s", "https://cdn/a.m4s"], tmp_path / "o.mkv", 60, VideoConfig())
    assert cmd.count("-i") == 2
    assert "-map" in cmd and "0:v:0" in cmd and "1:a:0" in cmd


def test_screen_command_includes_display_and_audio(tmp_path):
    cmd = build_screen_command(":99", "webrec_sink.monitor", tmp_path / "o.mkv", 30, VideoConfig())
    assert "x11grab" in cmd
    assert ":99.0+0,0" in cmd
    assert "pulse" in cmd and "webrec_sink.monitor" in cmd
    assert cmd[cmd.index("-video_size") + 1] == "1280x720"


def test_screen_command_without_audio(tmp_path):
    cmd = build_screen_command(":99", None, tmp_path / "o.mkv", 30, VideoConfig())
    assert "pulse" not in cmd
    assert "-c:a" not in cmd


# --------------------------------------------------------------- 주소 해석
def test_direct_media_url_needs_no_ytdlp():
    assert resolve_stream_urls("https://cdn.example.com/live.m3u8") == ["https://cdn.example.com/live.m3u8"]


def test_missing_ytdlp_gives_actionable_error(monkeypatch):
    monkeypatch.setattr("webrec.capture.ytdlp_path", lambda: None)
    with pytest.raises(CaptureError, match="yt-dlp"):
        resolve_stream_urls("https://www.youtube.com/watch?v=abc")


def test_ytdlp_failure_is_reported(monkeypatch):
    class Proc:
        returncode = 1
        stdout = ""
        stderr = "ERROR: This live event will begin in 3 hours."

    monkeypatch.setattr("webrec.capture.ytdlp_path", lambda: "/usr/bin/yt-dlp")
    monkeypatch.setattr("webrec.capture.run", lambda *a, **k: Proc())
    with pytest.raises(CaptureError, match="해석하지 못했"):
        resolve_stream_urls("https://www.youtube.com/watch?v=abc")


# --------------------------------------------------------------- 조각 합치기
@needs_ffmpeg
def test_concat_parts_merges_segments(tmp_path: Path):
    parts = [make_video(tmp_path / f"p{i}.mkv", seconds=2) for i in range(3)]
    out = tmp_path / "merged.mkv"
    result = concat_parts(parts, out)

    from webrec.verify import verify_recording
    verified = verify_recording(result)
    assert verified.ok, verified.summary()
    assert verified.metrics["duration_sec"] > 5  # 2초 x 3개
    assert not parts[0].exists()  # 합친 뒤 조각은 정리된다


@needs_ffmpeg
def test_concat_single_part_just_renames(tmp_path: Path):
    part = make_video(tmp_path / "only.mkv", seconds=2)
    out = tmp_path / "final.mkv"
    assert concat_parts([part], out) == out
    assert out.exists() and not part.exists()


@pytest.mark.parametrize("url,expected", [
    # 웨비나 링크(/w/)도 웹 클라이언트로 변환하고 등록 토큰(tk)을 유지해야 한다
    ("https://walmart.zoom.us/w/97608310562?tk=ABC&pwd=XYZ&uuid=UU",
     "https://walmart.zoom.us/wc/join/97608310562?tk=ABC&pwd=XYZ&uuid=UU"),
    ("https://zoom.us/my/someone", "https://zoom.us/wc/join/someone"),
])
def test_zoom_webinar_and_personal_links(url, expected):
    assert zoom_web_client_url(url) == expected
    assert plan_for(url).kind == "zoom"
    assert choose_backend(url, "auto")[0] == "browser"
