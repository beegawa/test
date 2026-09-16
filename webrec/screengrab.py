"""화면을 한 장 찍어 색 위치를 찾는 도구.

브라우저 창이 화면 어디에 있는지 '계산' 하면 환경마다(창 관리자 유무, 배율,
전체화면 여부) 어긋난다. 그래서 페이지에 잠깐 표식을 띄우고 화면을 한 장 찍어
그 표식이 실제로 어디에 찍히는지 '측정' 한다.
"""

from __future__ import annotations

import logging
import subprocess

from .tools import ffmpeg_path

log = logging.getLogger(__name__)


def grab_frame(
    *, display: str | None, width: int, height: int, timeout: int = 20
) -> bytes | None:
    """화면 한 장을 RGB 원본 픽셀로 가져온다."""
    cmd = [ffmpeg_path(), "-hide_banner", "-loglevel", "error"]
    env = None
    if display:  # 리눅스 가상 화면
        cmd += ["-f", "x11grab", "-video_size", f"{width}x{height}", "-i", f"{display}.0+0,0"]
        env = {"DISPLAY": display}
    else:        # Windows 실제 화면
        cmd += ["-f", "gdigrab", "-i", "desktop"]
    cmd += ["-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]

    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout, env=env)
    except (subprocess.TimeoutExpired, OSError) as exc:
        log.debug("화면 촬영 실패: %s", exc)
        return None
    data = proc.stdout
    if len(data) < width * height * 3:
        log.debug("화면 촬영 결과가 예상보다 작습니다: %d 바이트", len(data))
        return None
    return data[: width * height * 3]


def find_color_box(
    data: bytes, width: int, height: int, rgb: tuple[int, int, int], *, tolerance: int = 30
) -> tuple[int, int, int, int] | None:
    """찍힌 화면에서 해당 색이 차지하는 사각형 범위를 찾는다.

    반환: (x, y, 너비, 높이). 못 찾으면 None.
    """
    target_r, target_g, target_b = rgb
    min_x, min_y = width, height
    max_x = max_y = -1
    found = 0

    # 모든 픽셀을 보면 느리므로 2픽셀 간격으로 훑는다(경계는 아래에서 보정)
    step = 2
    for y in range(0, height, step):
        row = y * width * 3
        for x in range(0, width, step):
            index = row + x * 3
            if (
                abs(data[index] - target_r) <= tolerance
                and abs(data[index + 1] - target_g) <= tolerance
                and abs(data[index + 2] - target_b) <= tolerance
            ):
                found += 1
                if x < min_x: min_x = x
                if y < min_y: min_y = y
                if x > max_x: max_x = x
                if y > max_y: max_y = y

    if found < 100 or max_x < 0:
        return None
    # 간격 탐색으로 놓친 만큼 넓혀준다
    min_x = max(0, min_x - step)
    min_y = max(0, min_y - step)
    max_x = min(width - 1, max_x + step)
    max_y = min(height - 1, max_y + step)
    return min_x, min_y, max_x - min_x + 1, max_y - min_y + 1
