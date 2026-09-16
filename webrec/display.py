"""브라우저 캡처용 가상 화면(Xvfb)과 가상 오디오(PulseAudio null sink) 관리."""

from __future__ import annotations

import logging
import os
import random
import shutil
import signal
import subprocess
import time
from pathlib import Path

from .errors import CaptureError
from .tools import run, which

log = logging.getLogger(__name__)


class VirtualDisplay:
    """Xvfb 가상 디스플레이. 헤드리스 서버에서도 브라우저 화면을 캡처할 수 있게 한다."""

    def __init__(self, width: int, height: int, *, depth: int = 24):
        self.width = width
        self.height = height
        self.depth = depth
        self.display: str | None = None
        self._proc: subprocess.Popen | None = None

    def _pick_display(self) -> str:
        for _ in range(50):
            num = random.randint(90, 900)
            if not Path(f"/tmp/.X11-unix/X{num}").exists():
                return f":{num}"
        raise CaptureError("사용 가능한 X 디스플레이 번호를 찾지 못했습니다.")

    def start(self) -> str:
        xvfb = which("Xvfb")
        if not xvfb:
            raise CaptureError(
                "Xvfb 가 없어 브라우저 캡처를 할 수 없습니다. 설치: sudo apt-get install -y xvfb"
            )
        self.display = self._pick_display()
        cmd = [xvfb, self.display, "-screen", "0", f"{self.width}x{self.height}x{self.depth}", "-nolisten", "tcp"]
        log.info("가상 화면 시작: %s (%dx%d)", self.display, self.width, self.height)
        self._proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # 소켓이 생길 때까지 대기
        socket = Path(f"/tmp/.X11-unix/X{self.display.lstrip(':')}")
        for _ in range(100):
            if socket.exists():
                return self.display
            if self._proc.poll() is not None:
                raise CaptureError(f"Xvfb 가 즉시 종료되었습니다 (코드 {self._proc.returncode}).")
            time.sleep(0.1)
        raise CaptureError("Xvfb 가 10초 안에 준비되지 않았습니다.")

    def stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.send_signal(signal.SIGTERM)
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:  # pragma: no cover
                self._proc.kill()
        self._proc = None

    def __enter__(self) -> "VirtualDisplay":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()


class PulseSink:
    """브라우저 소리를 담을 PulseAudio 가상 출력(null sink).

    PulseAudio 가 없으면 조용히 비활성화되고, 녹화는 영상만 진행된다.
    """

    def __init__(self, name: str = "webrec_sink"):
        self.name = name
        self.module_id: str | None = None
        self._server_proc: subprocess.Popen | None = None

    @property
    def monitor(self) -> str | None:
        return f"{self.name}.monitor" if self.module_id else None

    def _ensure_server(self) -> bool:
        if not which("pulseaudio"):
            return False
        probe = run(["pactl", "info"], timeout=10) if which("pactl") else None
        if probe is not None and probe.returncode == 0:
            return True
        log.info("PulseAudio 데몬을 시작합니다.")
        self._server_proc = subprocess.Popen(
            ["pulseaudio", "--start", "--exit-idle-time=-1"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(30):
            time.sleep(0.3)
            if which("pactl") and run(["pactl", "info"], timeout=10).returncode == 0:
                return True
        return False

    def start(self) -> str | None:
        if not shutil.which("pactl") or not self._ensure_server():
            log.warning("PulseAudio 를 쓸 수 없습니다 - 소리 없이 영상만 녹화합니다.")
            return None
        proc = run(
            [
                "pactl", "load-module", "module-null-sink",
                f"sink_name={self.name}",
                f"sink_properties=device.description={self.name}",
            ],
            timeout=15,
        )
        if proc.returncode != 0:
            log.warning("가상 오디오 장치 생성 실패: %s", proc.stderr.strip()[:200])
            return None
        self.module_id = proc.stdout.strip()
        os.environ["PULSE_SINK"] = self.name
        log.info("가상 오디오 장치 준비 완료: %s", self.monitor)
        return self.monitor

    def stop(self) -> None:
        if self.module_id and shutil.which("pactl"):
            run(["pactl", "unload-module", self.module_id], timeout=15)
        self.module_id = None
        os.environ.pop("PULSE_SINK", None)

    def __enter__(self) -> "PulseSink":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()
