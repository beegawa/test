"""Windows 화면 캡처 로직 테스트.

실제 Windows 가 아니어도 명령 구성과 장치 선택은 검증할 수 있다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from webrec.config import VideoConfig
from webrec.wincapture import build_gdigrab_command, find_loopback_device, list_audio_devices

# ffmpeg -list_devices 출력 예시 (한국어 Windows)
FFMPEG_DEVICE_OUTPUT = """
[dshow @ 000001] "Integrated Camera" (video)
[dshow @ 000001]   Alternative name "@device_pnp_\\\\?\\usb#vid_04f2"
[dshow @ 000001] "마이크(Realtek(R) Audio)" (audio)
[dshow @ 000001] "스테레오 믹스(Realtek(R) Audio)" (audio)
"""

NO_LOOPBACK_OUTPUT = """
[dshow @ 000001] "마이크(Realtek(R) Audio)" (audio)
"""


class FakeProc:
    def __init__(self, stderr):
        self.returncode = 1        # 이 명령은 항상 오류로 끝난다
        self.stdout = ""
        self.stderr = stderr


@pytest.fixture
def video():
    return VideoConfig(resolution="1280x720", fps=25)


# ------------------------------------------------------------------ 장치 선택
def test_lists_audio_devices(monkeypatch):
    monkeypatch.setattr("webrec.wincapture.run", lambda *a, **k: FakeProc(FFMPEG_DEVICE_OUTPUT))
    devices = list_audio_devices()
    assert "스테레오 믹스(Realtek(R) Audio)" in devices
    assert "마이크(Realtek(R) Audio)" in devices
    assert "Integrated Camera" not in devices      # 영상 장치는 제외


def test_picks_stereo_mix_for_system_sound(monkeypatch):
    monkeypatch.setattr("webrec.wincapture.run", lambda *a, **k: FakeProc(FFMPEG_DEVICE_OUTPUT))
    assert find_loopback_device() == "스테레오 믹스(Realtek(R) Audio)"


def test_prefers_virtual_cable(monkeypatch):
    output = FFMPEG_DEVICE_OUTPUT + '[dshow @ 1] "CABLE Output (VB-Audio Virtual Cable)" (audio)\n'
    monkeypatch.setattr("webrec.wincapture.run", lambda *a, **k: FakeProc(output))
    assert "CABLE Output" in find_loopback_device()


def test_returns_none_without_loopback(monkeypatch):
    """마이크만 있으면 시스템 소리는 녹음할 수 없다 -> None (영상만 녹화)."""
    monkeypatch.setattr("webrec.wincapture.run", lambda *a, **k: FakeProc(NO_LOOPBACK_OUTPUT))
    assert find_loopback_device() is None


def test_explicit_device_wins(monkeypatch):
    monkeypatch.setattr("webrec.wincapture.run", lambda *a, **k: FakeProc(FFMPEG_DEVICE_OUTPUT))
    assert find_loopback_device("내가 고른 장치") == "내가 고른 장치"


def test_device_listing_survives_ffmpeg_failure(monkeypatch):
    def boom(*a, **k):
        raise OSError("ffmpeg 없음")

    monkeypatch.setattr("webrec.wincapture.run", boom)
    assert list_audio_devices() == []


# ------------------------------------------------------------------ 명령 구성
def test_captures_whole_desktop_by_default(video, tmp_path):
    cmd = build_gdigrab_command(tmp_path / "out.mkv", 600, video, audio_device="스테레오 믹스")
    assert "gdigrab" in cmd
    assert "desktop" in cmd                       # 창 제목을 안 주면 전체 화면
    assert cmd[cmd.index("-t") + 1] == "600"
    assert "dshow" in cmd and "audio=스테레오 믹스" in cmd


def test_captures_single_window_when_title_given(video, tmp_path):
    cmd = build_gdigrab_command(tmp_path / "o.mkv", 60, video, window_title="Zoom 회의")
    assert "title=Zoom 회의" in cmd
    assert "desktop" not in cmd


def test_scales_screen_to_requested_resolution(video, tmp_path):
    cmd = build_gdigrab_command(tmp_path / "o.mkv", 60, video)
    filters = cmd[cmd.index("-vf") + 1]
    assert "scale=1280:720" in filters
    assert "pad=1280:720" in filters               # 화면 비율이 달라도 찌그러지지 않게


def test_no_audio_when_device_missing(video, tmp_path):
    cmd = build_gdigrab_command(tmp_path / "o.mkv", 60, video, audio_device=None)
    assert "dshow" not in cmd
    assert "-c:a" not in cmd


def test_no_audio_when_disabled_in_settings(tmp_path):
    silent = VideoConfig(resolution="1280x720", fps=25, audio=False)
    cmd = build_gdigrab_command(tmp_path / "o.mkv", 60, silent, audio_device="스테레오 믹스")
    assert "dshow" not in cmd


def test_region_and_offset(video, tmp_path):
    cmd = build_gdigrab_command(tmp_path / "o.mkv", 60, video, offset=(100, 50), region=(800, 600))
    assert cmd[cmd.index("-offset_x") + 1] == "100"
    assert cmd[cmd.index("-video_size") + 1] == "800x600"


# --------------------------------------------------- 운영체제별 경로 선택
def test_windows_uses_gdigrab_and_no_virtual_display(tmp_path, monkeypatch):
    """Windows 에서는 Xvfb 없이 실제 화면(gdigrab)을 캡처해야 한다."""
    from unittest import mock

    import webrec.capture as cap
    from webrec.config import build_config

    job = build_config({"jobs": [{
        "name": "윈도우", "url": "https://zoom.us/j/123", "duration": "1h", "backend": "browser",
    }]}, require_schedule=False).jobs[0]

    captured = {}

    def fake_loop(job, out, dur, logf, retries, make_cmd, env=None):
        captured["cmd"] = make_cmd(tmp_path / "out.mkv", dur)
        return [tmp_path / "out.mkv"], 1, 1.0, "", 0

    with mock.patch.object(cap, "is_windows", return_value=True), \
         mock.patch.object(cap, "find_loopback_device", return_value="스테레오 믹스"), \
         mock.patch.object(cap, "BrowserSession") as session, \
         mock.patch.object(cap, "_record_loop", fake_loop), \
         mock.patch.object(cap, "concat_parts", lambda parts, out: out), \
         mock.patch.object(cap, "VirtualDisplay", side_effect=AssertionError("Xvfb 를 쓰면 안 된다")):
        browser = mock.MagicMock()
        browser.capture_region.return_value = None      # 전체 화면
        browser.notes, browser.warnings = [], []
        session.return_value.__enter__.return_value = browser
        result = cap.capture(job, tmp_path / "out.mkv", 3600, backend="browser")

    cmd = captured["cmd"]
    assert "gdigrab" in cmd and "x11grab" not in cmd
    assert cmd[cmd.index("-i") + 1] == "desktop"
    assert "audio=스테레오 믹스" in cmd
    assert session.call_args.kwargs["display"] is None     # 가상 화면 없음
    assert result.backend == "browser"


def test_linux_still_uses_virtual_display(tmp_path, monkeypatch):
    """리눅스 경로는 그대로 Xvfb + x11grab 을 쓴다."""
    from unittest import mock

    import webrec.capture as cap
    from webrec.config import build_config

    job = build_config({"jobs": [{
        "name": "리눅스", "url": "https://zoom.us/j/123", "duration": "1h", "backend": "browser",
    }]}, require_schedule=False).jobs[0]

    captured = {}

    def fake_loop(job, out, dur, logf, retries, make_cmd, env=None):
        captured["cmd"] = make_cmd(tmp_path / "out.mkv", dur)
        return [tmp_path / "out.mkv"], 1, 1.0, "", 0

    with mock.patch.object(cap, "is_windows", return_value=False), \
         mock.patch.object(cap, "VirtualDisplay") as display, \
         mock.patch.object(cap, "PulseSink"), \
         mock.patch.object(cap, "BrowserSession") as session, \
         mock.patch.object(cap, "_record_loop", fake_loop), \
         mock.patch.object(cap, "concat_parts", lambda parts, out: out):
        display.return_value.__enter__.return_value.display = ":99"
        browser = mock.MagicMock()
        browser.capture_region.return_value = None
        browser.notes, browser.warnings = [], []
        session.return_value.__enter__.return_value = browser
        cap.capture(job, tmp_path / "out.mkv", 3600, backend="browser")

    assert "x11grab" in captured["cmd"]
    assert session.call_args.kwargs["display"] == ":99"


# ------------------------------------------------- 설치 위치 자동 탐색
def test_env_override_points_to_file(tmp_path, monkeypatch):
    """WEBREC_FFMPEG 로 실행 파일을 직접 지정할 수 있다."""
    from webrec.tools import find_tool

    exe = tmp_path / "ffmpeg"
    exe.write_text("#!/bin/sh\n")
    monkeypatch.setenv("WEBREC_FFMPEG", str(exe))
    assert find_tool("ffmpeg") == str(exe)


def test_env_override_points_to_folder(tmp_path, monkeypatch):
    """폴더를 지정해도 그 안에서 찾아준다."""
    from webrec.tools import find_tool

    (tmp_path / "ffmpeg.exe").write_text("")
    monkeypatch.setenv("WEBREC_FFMPEG", str(tmp_path))
    assert find_tool("ffmpeg") == str(tmp_path / "ffmpeg.exe")


def test_finds_ffmpeg_downloaded_into_project(tmp_path, monkeypatch):
    """설치 스크립트가 프로그램 폴더에 받아둔 ffmpeg 를 PATH 없이도 찾는다."""
    import webrec.tools as tools

    bundled = tmp_path / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
    bundled.parent.mkdir(parents=True)
    bundled.write_text("")

    monkeypatch.delenv("WEBREC_FFMPEG", raising=False)
    monkeypatch.setattr(tools, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(tools.sys, "platform", "win32")
    monkeypatch.setattr(tools.shutil, "which", lambda name: None)   # PATH 에는 없음

    assert tools.find_tool("ffmpeg") == str(bundled)


def test_finds_ffmpeg_installed_by_winget(tmp_path, monkeypatch):
    """winget 이 버전 폴더에 풀어놓은 ffmpeg 도 찾아낸다."""
    import webrec.tools as tools

    winget = tmp_path / "Microsoft" / "WinGet" / "Packages" / "Gyan.FFmpeg_1.0" / "ffmpeg-7.0" / "bin"
    winget.mkdir(parents=True)
    (winget / "ffmpeg.exe").write_text("")

    monkeypatch.delenv("WEBREC_FFMPEG", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(tools, "_PROJECT_ROOT", tmp_path / "없는폴더")
    monkeypatch.setattr(tools.sys, "platform", "win32")
    monkeypatch.setattr(tools.shutil, "which", lambda name: None)

    assert tools.find_tool("ffmpeg") == str(winget / "ffmpeg.exe")


def test_missing_tool_message_mentions_installer(monkeypatch):
    """ffmpeg 가 없을 때 안내가 설치 방법을 알려준다."""
    import webrec.tools as tools
    from webrec.errors import ToolMissingError

    monkeypatch.delenv("WEBREC_FFMPEG", raising=False)
    monkeypatch.setattr(tools, "find_tool", lambda name: None)
    with pytest.raises(ToolMissingError, match="예약녹화-시작.bat"):
        tools.ffmpeg_path()
