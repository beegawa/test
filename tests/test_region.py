"""녹화 영역 계산 테스트."""

from __future__ import annotations

import pytest

from webrec.config import build_config
from webrec.errors import ConfigError
from webrec.screengrab import find_color_box
from webrec.sites import _parse_region


def _rgb_image(width, height, background, box=None, box_color=(255, 0, 255)):
    """테스트용 원본 RGB 이미지를 만든다. box=(x,y,w,h)."""
    data = bytearray()
    for y in range(height):
        for x in range(width):
            inside = box and box[0] <= x < box[0] + box[2] and box[1] <= y < box[1] + box[3]
            data.extend(box_color if inside else background)
    return bytes(data)


# ------------------------------------------------------------------ 색 찾기
def test_finds_marker_box():
    image = _rgb_image(200, 100, (0, 0, 0), box=(40, 20, 100, 60))
    found = find_color_box(image, 200, 100, (255, 0, 255))
    assert found is not None
    x, y, width, height = found
    # 2픽셀 간격으로 훑으므로 약간의 오차는 허용한다
    assert abs(x - 40) <= 4 and abs(y - 20) <= 4
    assert abs(width - 100) <= 8 and abs(height - 60) <= 8


def test_returns_none_when_marker_absent():
    image = _rgb_image(100, 50, (10, 10, 10))
    assert find_color_box(image, 100, 50, (255, 0, 255)) is None


def test_ignores_few_stray_pixels():
    """비슷한 색 몇 점은 표식으로 보지 않는다."""
    image = _rgb_image(200, 100, (0, 0, 0), box=(0, 0, 3, 3))
    assert find_color_box(image, 200, 100, (255, 0, 255)) is None


def test_tolerates_slight_color_shift():
    """화면 캡처로 색이 살짝 달라져도 찾아낸다."""
    image = _rgb_image(120, 80, (0, 0, 0), box=(10, 10, 60, 40), box_color=(250, 8, 248))
    assert find_color_box(image, 120, 80, (255, 0, 255)) is not None


# -------------------------------------------------------------- 영역 문자열
@pytest.mark.parametrize("text,expected", [
    ("100,50,640,360", (100, 50, 640, 360)),
    ("0,0,1920,1080", (0, 0, 1920, 1080)),
    ("10, 20, 641, 361", (10, 20, 640, 360)),   # 홀수는 짝수로 (h264 요구)
])
def test_parses_region_text(text, expected):
    assert _parse_region(text) == expected


@pytest.mark.parametrize("text", [None, "", "100,50", "a,b,c,d", "1,2,3,4,5"])
def test_rejects_bad_region_text(text):
    assert _parse_region(text) is None


# ------------------------------------------------------------------ 설정
def _job(**browser):
    return build_config({"jobs": [{
        "name": "t", "url": "https://example.com/live", "duration": "1h",
        "backend": "browser", "browser": browser,
    }]}, require_schedule=False).jobs[0]


def test_capture_mode_defaults_to_auto():
    assert _job().browser.capture == "auto"


@pytest.mark.parametrize("mode", ["auto", "video", "screen", "region"])
def test_accepts_capture_modes(mode):
    browser = {"capture": mode}
    if mode == "region":
        browser["region"] = "0,0,640,360"
    assert _job(**browser).browser.capture == mode


def test_rejects_unknown_capture_mode():
    with pytest.raises(ConfigError, match="capture"):
        _job(capture="영상만요")


def test_region_mode_requires_coordinates():
    with pytest.raises(ConfigError, match="region"):
        _job(capture="region")
