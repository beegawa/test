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
