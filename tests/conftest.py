"""테스트 공용 픽스처 - ffmpeg 로 테스트용 영상을 만든다."""

from __future__ import annotations

import functools
import http.server
import socketserver
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FFMPEG = shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg 가 설치되어 있지 않습니다.")


def make_video(path: Path, *, seconds: int = 5, black: bool = False, silent: bool = True) -> Path:
    """검증 테스트용 짧은 영상 생성."""
    video_src = f"color=c=black:s=640x480:r=25:d={seconds}" if black else f"testsrc=size=640x480:rate=25:d={seconds}"
    audio_src = (
        f"anullsrc=r=44100:cl=stereo:d={seconds}" if silent else f"sine=frequency=440:r=44100:d={seconds}"
    )
    cmd = [
        FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", video_src,
        "-f", "lavfi", "-i", audio_src,
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", "-movflags", "+faststart", str(path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return path


@pytest.fixture
def sample_video(tmp_path: Path) -> Path:
    return make_video(tmp_path / "sample.mp4", seconds=5, silent=False)


@pytest.fixture
def black_video(tmp_path: Path) -> Path:
    return make_video(tmp_path / "black.mp4", seconds=5, black=True)


class RecordingMailer:
    """실제 SMTP 대신 발송 내역만 모아두는 테스트용 메일러."""

    def __init__(self):
        self.sent: list[dict] = []
        self.dry_run = False

    def send(self, notify, subject, body, *, attachments=None):
        self.sent.append(
            {"to": list(notify.to), "subject": subject, "body": body, "attachments": attachments or []}
        )
        return True

    def subjects(self) -> list[str]:
        return [item["subject"] for item in self.sent]


@pytest.fixture
def mailer() -> RecordingMailer:
    return RecordingMailer()


@pytest.fixture
def media_server(tmp_path: Path):
    """테스트용 영상을 제공하는 임시 HTTP 서버."""
    root = tmp_path / "www"
    root.mkdir()
    make_video(root / "live.mp4", seconds=30)
    make_video(root / "black.mp4", seconds=30, black=True)

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
