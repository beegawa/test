"""사이트별 처리.

- Zoom 초대 링크를 브라우저(웹 클라이언트) 주소로 바꾸고 이름/암호를 채워 입장
- YouTube 등 일반 페이지는 재생 버튼/쿠키 배너 처리 후 전체화면
자동 조작은 모두 '최선 노력(best effort)' 이며, 실패해도 녹화 자체는 계속된다.
"""

from __future__ import annotations

import logging
import re
import subprocess
import time
from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse

from .errors import CaptureError
from .tools import browser_path

log = logging.getLogger(__name__)

ZOOM_HOST_RE = re.compile(r"(^|\.)(zoom\.us|zoomgov\.com)$", re.IGNORECASE)
ZOOM_JOIN_RE = re.compile(r"/(j|wc/join|my)/(?P<id>[A-Za-z0-9._-]+)")

# yt-dlp 로 직접 스트림 주소를 얻을 수 있는(=stream 백엔드가 유리한) 대표 사이트
STREAMABLE_HOSTS = (
    "youtube.com", "youtu.be", "twitch.tv", "vimeo.com", "afreecatv.com",
    "chzzk.naver.com", "tv.naver.com", "kick.com", "dailymotion.com", "facebook.com",
)

DIRECT_MEDIA_SUFFIXES = (".m3u8", ".mpd", ".mp4", ".ts", ".flv", ".webm")


@dataclass
class SitePlan:
    """URL 을 보고 정한 캡처 전략."""

    kind: str          # zoom | stream | generic
    launch_url: str    # 브라우저에 띄울 주소
    source_url: str    # 원본 주소
    recommended_backend: str


def plan_for(url: str) -> SitePlan:
    """URL 종류를 판별해 권장 백엔드와 실제 접속 주소를 정한다."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()

    if ZOOM_HOST_RE.search(host):
        return SitePlan("zoom", zoom_web_client_url(url), url, "browser")

    if any(url.lower().split("?")[0].endswith(suffix) for suffix in DIRECT_MEDIA_SUFFIXES):
        return SitePlan("stream", url, url, "stream")

    if any(host == h or host.endswith("." + h) for h in STREAMABLE_HOSTS):
        return SitePlan("stream", url, url, "stream")

    return SitePlan("generic", url, url, "stream")


def zoom_web_client_url(url: str) -> str:
    """Zoom 초대 링크를 브라우저 웹 클라이언트 주소(/wc/join/<회의번호>)로 변환."""
    parsed = urlparse(url)
    match = ZOOM_JOIN_RE.search(parsed.path)
    if not match:
        return url
    meeting_id = match.group("id")
    path = f"/wc/join/{meeting_id}"
    return urlunparse(parsed._replace(path=path))


class BrowserSession:
    """가상 화면 위에 브라우저를 띄우고 사이트에 입장시킨다.

    Playwright 가 설치돼 있으면 클릭/입력 자동화를 하고, 없으면 브라우저를
    kiosk 모드로 실행만 한다(암호 없는 공개 라이브에는 이것으로 충분하다).
    """

    def __init__(self, plan: SitePlan, *, display: str, video, browser_cfg):
        self.plan = plan
        self.display = display
        self.video = video
        self.cfg = browser_cfg
        self._playwright = None
        self._browser = None
        self._page = None
        self._proc: subprocess.Popen | None = None
        self.automated = False

    # ---------------------------------------------------------------- 실행
    def start(self) -> None:
        if self._start_playwright():
            self.automated = True
            return
        self._start_plain()

    def _chrome_args(self) -> list[str]:
        import os

        args = [
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-infobars",
            "--disable-session-crashed-bubble",
            "--disable-notifications",
            "--autoplay-policy=no-user-gesture-required",
            "--use-fake-ui-for-media-stream",  # 카메라/마이크 권한 자동 허용
            "--start-fullscreen",
            "--kiosk",
            f"--window-size={self.video.width},{self.video.height}",
            "--window-position=0,0",
        ]
        # 컨테이너/서버 환경 대응 (root 로 돌면 샌드박스를 끌 수밖에 없다)
        args.append("--disable-dev-shm-usage")
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            args += ["--no-sandbox", "--disable-gpu"]
        if self.cfg.mute_page:
            args.append("--mute-audio")
        args.extend(self.cfg.extra_args)
        return args

    def _start_playwright(self) -> bool:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            log.info("playwright 가 없어 브라우저 자동 조작 없이 실행합니다.")
            return False

        try:
            self._playwright = sync_playwright().start()
            launch_kwargs = {
                "headless": False,  # 화면을 캡처해야 하므로 반드시 headed
                "args": self._chrome_args(),
                "env": {"DISPLAY": self.display},
            }
            executable = self.cfg.executable_path or browser_path()
            if executable:
                launch_kwargs["executable_path"] = executable
            self._browser = self._playwright.chromium.launch(**launch_kwargs)
            context = self._browser.new_context(
                viewport={"width": self.video.width, "height": self.video.height},
                permissions=["camera", "microphone"],
            )
            self._page = context.new_page()
            log.info("브라우저 접속: %s", self.plan.launch_url)
            self._page.goto(self.plan.launch_url, wait_until="domcontentloaded", timeout=60_000)
            return True
        except Exception as exc:
            log.warning("Playwright 실행 실패(%s) - 기본 브라우저 실행으로 대체합니다.", exc)
            self.close()
            return False

    def _start_plain(self) -> None:
        executable = browser_path(self.cfg.executable_path)
        if not executable:
            raise CaptureError(
                "브라우저를 찾지 못했습니다. chromium 설치 후 다시 시도하세요 "
                "(sudo apt-get install -y chromium-browser) 또는 WEBREC_BROWSER 환경변수로 경로 지정."
            )
        cmd = [executable] + self._chrome_args() + [self.plan.launch_url]
        log.info("브라우저 실행: %s", executable)
        self._proc = subprocess.Popen(
            cmd,
            env={**_clean_env(), "DISPLAY": self.display},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    # ------------------------------------------------------------ 사이트 입장
    def enter(self) -> None:
        """페이지 로딩 후 사이트별 입장 절차를 수행."""
        if not self.automated or self._page is None:
            time.sleep(self.cfg.page_load_wait)
            return

        try:
            if self.plan.kind == "zoom":
                self._join_zoom()
            else:
                self._prepare_generic()
        except Exception as exc:  # 자동화 실패가 녹화 실패로 이어지면 안 된다
            log.warning("사이트 자동 입장 중 문제가 있었습니다(무시하고 진행): %s", exc)

        time.sleep(self.cfg.page_load_wait)

    def _join_zoom(self) -> None:
        page = self._page
        assert page is not None
        log.info("Zoom 웹 클라이언트 입장 시도 (이름: %s)", self.cfg.display_name)

        # '브라우저에서 참가' 링크가 먼저 뜨는 경우
        for selector in ("text=Join from Your Browser", "text=브라우저에서 참가", "a.webclient"):
            try:
                link = page.locator(selector).first
                if link.is_visible(timeout=2_000):
                    link.click()
                    page.wait_for_timeout(2_000)
                    break
            except Exception:
                continue

        name_selectors = ("#input-for-name", "input[name='inputname']", "input#inputname", "input[type='text']")
        for selector in name_selectors:
            try:
                box = page.locator(selector).first
                if box.is_visible(timeout=3_000):
                    box.fill(self.cfg.display_name)
                    break
            except Exception:
                continue

        if self.cfg.passcode:
            for selector in ("#input-for-pwd", "input[name='inputpasscode']", "input[type='password']"):
                try:
                    box = page.locator(selector).first
                    if box.is_visible(timeout=2_000):
                        box.fill(self.cfg.passcode)
                        break
                except Exception:
                    continue

        for selector in ("button.preview-join-button", "#joinBtn", "text=Join", "text=참가"):
            try:
                button = page.locator(selector).first
                if button.is_visible(timeout=3_000):
                    button.click()
                    break
            except Exception:
                continue

        page.wait_for_timeout(5_000)

        # 입장 후 '컴퓨터 오디오로 참가' 처리 (소리 캡처에 필요)
        for selector in ("text=Join Audio by Computer", "text=컴퓨터 오디오로 참가", "button.join-audio-by-voip__join-btn"):
            try:
                button = page.locator(selector).first
                if button.is_visible(timeout=5_000):
                    button.click()
                    break
            except Exception:
                continue

    def _prepare_generic(self) -> None:
        page = self._page
        assert page is not None

        # 쿠키/동의 배너 닫기
        for selector in ("button:has-text('Accept all')", "button:has-text('모두 수락')", "button[aria-label='Accept all']"):
            try:
                button = page.locator(selector).first
                if button.is_visible(timeout=2_000):
                    button.click()
                    page.wait_for_timeout(1_000)
                    break
            except Exception:
                continue

        # 재생 시작 + 전체화면 (YouTube 등)
        try:
            page.keyboard.press("k")
        except Exception:
            pass
        try:
            player = page.locator("video").first
            if player.is_visible(timeout=5_000):
                player.click()
                page.wait_for_timeout(500)
                page.keyboard.press("f")
        except Exception:
            pass

    # ------------------------------------------------------------------ 종료
    def close(self) -> None:
        for closer in (self._close_browser, self._close_playwright, self._close_proc):
            try:
                closer()
            except Exception as exc:  # pragma: no cover
                log.debug("브라우저 정리 중 무시된 오류: %s", exc)

    def _close_browser(self) -> None:
        if self._browser is not None:
            self._browser.close()
            self._browser = None
            self._page = None

    def _close_playwright(self) -> None:
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None

    def _close_proc(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:  # pragma: no cover
                self._proc.kill()
        self._proc = None

    def __enter__(self) -> "BrowserSession":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def _clean_env() -> dict:
    import os

    env = dict(os.environ)
    env.pop("DISPLAY", None)
    return env
