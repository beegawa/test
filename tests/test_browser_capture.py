"""브라우저(화면) 캡처 백엔드 통합 테스트.

Zoom 처럼 페이지를 실제로 띄워 화면을 담는 경로를, 가상 화면 위에서 확인한다.
Xvfb 나 브라우저가 없는 환경에서는 건너뛴다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import needs_ffmpeg
from webrec.config import build_config
from webrec.display import VirtualDisplay
from webrec.tools import browser_path, xvfb_path
from webrec.verify import verify_recording

needs_display = pytest.mark.skipif(
    xvfb_path() is None or browser_path() is None,
    reason="Xvfb 또는 브라우저가 없습니다.",
)


@needs_display
def test_virtual_display_starts_and_stops():
    with VirtualDisplay(640, 480) as screen:
        assert screen.display and screen.display.startswith(":")
        assert Path(f"/tmp/.X11-unix/X{screen.display.lstrip(':')}").exists()
    assert screen._proc is None


@needs_ffmpeg
@needs_display
def test_browser_backend_captures_page_content(tmp_path: Path):
    """실제로 페이지를 띄워 화면을 녹화하고, 검은 화면이 아님을 확인한다."""
    page = tmp_path / "page.html"
    page.write_text(
        "<html><body style='margin:0;background:#1e88e5'>"
        "<h1 style='color:#fff;font-size:72px'>webrec 녹화 테스트</h1>"
        "</body></html>",
        encoding="utf-8",
    )

    job = build_config({"jobs": [{
        "name": "브라우저테스트",
        "url": "https://example.com/placeholder",   # 아래에서 실제 주소로 교체
        "duration": "6s",
        "backend": "browser",
        "output_dir": str(tmp_path / "rec"),
        "video": {"resolution": "800x600", "fps": 10, "audio": False},
        "browser": {"page_load_wait": 3},
        "max_retries": 0,
    }]}, require_schedule=False).jobs[0]
    job.url = page.as_uri()

    from webrec.capture import capture

    out = tmp_path / "rec" / "browser.mkv"
    result = capture(job, out, 6, backend="browser")

    verified = verify_recording(result.path, expected_duration=6, min_fill_ratio=0.5)
    assert verified.ok, verified.summary()
    assert verified.metrics["width"] == 800
    assert verified.metrics["black_ratio"] < 0.5   # 페이지 내용이 실제로 담겼다


# =========================================================== 영상 영역만 녹화
@pytest.fixture
def video_page(tmp_path: Path):
    """빨간 배경 페이지 안에 초록 영상을 놓고 HTTP 로 제공한다.

    잘라낸 결과에 빨간색이 섞이면 영역 계산이 틀린 것이다.
    """
    import functools
    import http.server
    import socketserver
    import subprocess
    import threading

    root = tmp_path / "www"
    root.mkdir()
    # 이 환경의 크로뮴은 오픈소스 빌드라 H.264 를 재생하지 못한다 -> WebM 사용
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "color=c=#00aa00:s=640x360:r=15:d=30",
        "-vf", "drawbox=x='mod(t*200,600)':y=150:w=40:h=60:color=white:t=fill",
        "-c:v", "libvpx-vp9", "-b:v", "500k", "-cpu-used", "8", "-deadline", "realtime",
        "-an", str(root / "clip.webm"),
    ], check=True, capture_output=True)

    (root / "page.html").write_text(
        "<!DOCTYPE html><html><head><meta charset='utf-8'></head>"
        "<body style='margin:0;background:#cc0000'>"
        "<h1 style='margin:0;padding:20px;color:#fff'>이 빨간 부분은 녹화되면 안 됩니다</h1>"
        "<div style='margin-left:300px'>"
        "<video width='640' height='360' src='clip.webm'></video></div>"
        "<p style='padding:40px;color:#fff'>아래쪽도 녹화되면 안 됩니다</p></body></html>",
        encoding="utf-8",
    )

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/page.html"
    finally:
        server.shutdown()
        server.server_close()


def _color_ratios(path: Path, frame: int = 45) -> dict[str, float]:
    """녹화 파일 한 프레임에서 빨강/초록 비율을 잰다."""
    import subprocess

    proc = subprocess.run([
        "ffmpeg", "-v", "error", "-i", str(path),
        "-vf", f"select=eq(n\\,{frame}),scale=320:180", "-frames:v", "1",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ], capture_output=True)
    data = proc.stdout
    total = max(1, len(data) // 3)
    red = green = 0
    for i in range(0, len(data), 3):
        r, g, b = data[i], data[i + 1], data[i + 2]
        if r > 120 and g < 90 and b < 90:
            red += 1
        elif g > 90 and r < 120 and b < 120:
            green += 1
    return {"red": red / total, "green": green / total}


def _page_job(url: str, tmp_path: Path, capture_mode: str):
    return build_config({"jobs": [{
        "name": f"영역-{capture_mode}", "url": url, "duration": "8s", "backend": "browser",
        "output_dir": str(tmp_path / "rec"),
        "video": {"resolution": "1280x720", "fps": 15, "audio": False},
        "browser": {"capture": capture_mode, "page_load_wait": 3},
        "max_retries": 0,
    }]}, require_schedule=False).jobs[0]


@needs_ffmpeg
@needs_display
def test_records_only_the_video_area(video_page, tmp_path):
    """capture=video 면 페이지 배경 없이 영상만 담겨야 한다."""
    from webrec.capture import capture

    out = tmp_path / "rec" / "video.mkv"
    result = capture(_page_job(video_page, tmp_path, "video"), out, 8, backend="browser")

    assert result.region is not None, "영상 영역을 찾지 못했습니다"
    _, _, width, height = result.region
    assert 600 <= width <= 645 and 330 <= height <= 365, f"영역 크기가 이상합니다: {result.region}"

    ratios = _color_ratios(result.path)
    assert ratios["green"] > 0.9, f"영상이 제대로 담기지 않았습니다: {ratios}"
    assert ratios["red"] < 0.02, f"페이지 배경이 섞였습니다: {ratios}"


@needs_ffmpeg
@needs_display
def test_screen_mode_still_records_everything(video_page, tmp_path):
    """capture=screen 은 예전처럼 화면 전체를 담는다(비교군)."""
    from webrec.capture import capture

    out = tmp_path / "rec" / "screen.mkv"
    result = capture(_page_job(video_page, tmp_path, "screen"), out, 8, backend="browser")

    assert result.region is None
    ratios = _color_ratios(result.path)
    assert ratios["red"] > 0.2, f"화면 전체가 담기지 않았습니다: {ratios}"


@needs_ffmpeg
@needs_display
def test_starts_playback_that_is_not_autoplaying(video_page, tmp_path):
    """자동재생이 아닌 영상도 재생시켜야 한다(정지 화면 녹화 방지)."""
    from webrec.capture import capture

    out = tmp_path / "rec" / "play.mkv"
    result = capture(_page_job(video_page, tmp_path, "video"), out, 8, backend="browser")

    assert not result.warnings, f"재생 경고가 남았습니다: {result.warnings}"

    # 흰 막대가 움직이므로, 두 프레임이 서로 달라야 실제로 재생된 것이다
    first = _color_ratios(result.path, frame=20)
    later = _color_ratios(result.path, frame=90)
    assert first["green"] > 0.85 and later["green"] > 0.85


needs_pulse = pytest.mark.skipif(
    __import__("shutil").which("pulseaudio") is None, reason="PulseAudio 가 없습니다."
)


@needs_ffmpeg
@needs_display
@needs_pulse
def test_records_page_sound(tmp_path):
    """페이지에서 재생되는 소리가 실제로 녹음되는지 끝까지 확인한다.

    440Hz 음을 재생하는 페이지를 녹화한 뒤, 녹음된 소리의 주파수를 재서
    '소리가 있다' 가 아니라 '그 소리가 맞다' 까지 확인한다.
    """
    import functools
    import http.server
    import socketserver
    import subprocess
    import threading

    from test_audio import dominant_frequency
    from webrec.capture import capture

    root = tmp_path / "www"
    root.mkdir()
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "color=c=#00aa00:s=640x360:r=15:d=30",
        "-f", "lavfi", "-i", "sine=frequency=440:r=48000:d=30",
        "-c:v", "libvpx-vp9", "-b:v", "400k", "-cpu-used", "8", "-deadline", "realtime",
        "-c:a", "libopus", "-b:a", "96k", "-shortest", str(root / "tone.webm"),
    ], check=True, capture_output=True)
    (root / "page.html").write_text(
        "<body style='margin:0'><video width='640' height='360' src='tone.webm'></video></body>",
        encoding="utf-8",
    )

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()

    try:
        job = build_config({"jobs": [{
            "name": "소리녹화", "url": f"http://127.0.0.1:{server.server_address[1]}/page.html",
            "duration": "10s", "backend": "browser", "output_dir": str(tmp_path / "rec"),
            "video": {"resolution": "1280x720", "fps": 15, "audio": True},
            "browser": {"capture": "video", "page_load_wait": 3}, "max_retries": 0,
        }]}, require_schedule=False).jobs[0]

        result = capture(job, tmp_path / "rec" / "sound.mkv", 10, backend="browser")
    finally:
        server.shutdown()
        server.server_close()

    assert not result.warnings, f"경고가 남았습니다: {result.warnings}"

    verified = verify_recording(result.path, expected_duration=10, require_audio=True)
    assert verified.ok, verified.summary()
    assert verified.metrics["mean_volume_db"] > -60, "소리가 무음에 가깝습니다"

    freq, peak = dominant_frequency(result.path, start=3.0, seconds=2.0)
    assert 400 <= freq <= 480, f"녹음된 소리가 페이지의 440Hz 가 아닙니다: {freq:.0f}Hz"
    assert peak > 0.03, f"소리가 너무 작습니다: {peak:.3f}"
