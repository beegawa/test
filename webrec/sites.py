"""사이트별 처리.

- Zoom 초대 링크를 브라우저(웹 클라이언트) 주소로 바꾸고 이름/암호를 채워 입장
- YouTube 등 일반 페이지는 재생 버튼/쿠키 배너 처리 후 전체화면
자동 조작은 모두 '최선 노력(best effort)' 이며, 실패해도 녹화 자체는 계속된다.
"""

from __future__ import annotations

import logging
import re
import socket
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import quote, urlparse, urlsplit, urlunparse

from .errors import CaptureError
from .screengrab import find_color_box, grab_frame
from .tools import browser_path

log = logging.getLogger(__name__)

ZOOM_HOST_RE = re.compile(r"(^|\.)(zoom\.us|zoomgov\.com)$", re.IGNORECASE)
# 회의(/j/), 웨비나(/w/), 개인 링크(/my/), 이미 변환된 웹 클라이언트 주소(/wc/join/)
ZOOM_JOIN_RE = re.compile(r"/(wc/join|j|w|my)/(?P<id>[A-Za-z0-9._-]+)")

# yt-dlp 로 직접 스트림 주소를 얻을 수 있는(=stream 백엔드가 유리한) 대표 사이트
STREAMABLE_HOSTS = (
    "youtube.com", "youtu.be", "twitch.tv", "vimeo.com", "afreecatv.com",
    "chzzk.naver.com", "tv.naver.com", "kick.com", "dailymotion.com", "facebook.com",
)

DIRECT_MEDIA_SUFFIXES = (".m3u8", ".mpd", ".mp4", ".ts", ".flv", ".webm")



# 일반 브라우저처럼 보이게 한다(기본 User-Agent 는 차단하는 사이트가 많다)
_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def encode_url(url: str) -> str:
    """한글 등 ASCII 가 아닌 문자가 든 주소를 퍼센트 인코딩한다."""
    try:
        url.encode("ascii")
        return url
    except UnicodeEncodeError:
        parts = urlsplit(url)
        return parts._replace(
            path=quote(parts.path, safe="/%:@!$&'()*+,;="),
            query=quote(parts.query, safe="/%:@!$&'()*+,;=?"),
            fragment=quote(parts.fragment, safe="/%"),
        ).geturl()


def check_reachable(url: str, *, timeout: int = 15) -> tuple[str, str]:
    """주소에 실제로 접속되는지 미리 확인한다.

    브라우저 캡처는 페이지가 안 열려도 '에러 페이지'가 녹화되기 때문에
    화면만 봐서는 실패를 알아채기 어렵다. 그래서 캡처 전에 한 번 찔러본다.

    반환: (등급, 설명). 등급은 "ok" / "warn" / "fail".
      fail - DNS·연결·프록시·타임아웃 등 아예 접속이 안 되는 경우
      warn - 접속은 됐지만 4xx/5xx (봇 차단이거나 만료된 링크일 수 있음)
    """
    if url.startswith("file://"):
        return "ok", "로컬 파일"

    request = urllib.request.Request(encode_url(url), method="GET", headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response.read(2048)
            return "ok", f"HTTP {response.status} ({response.url.split('?')[0]})"
    except urllib.error.HTTPError as exc:
        return "warn", f"HTTP {exc.code} - 링크가 만료됐거나 자동 접속을 막는 사이트일 수 있습니다"
    except urllib.error.URLError as exc:
        return "fail", f"접속 불가: {exc.reason}"
    except (socket.timeout, TimeoutError):
        return "fail", f"{timeout}초 안에 응답이 없습니다"
    except Exception as exc:  # pragma: no cover - 예상 못 한 네트워크 오류
        return "fail", f"{type(exc).__name__}: {exc}"


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
    """Zoom 초대 링크를 브라우저 웹 클라이언트 주소(/wc/join/<번호>)로 변환.

    회의(/j/)와 웨비나(/w/) 모두 지원하며, 등록 토큰(tk)·암호(pwd) 같은
    쿼리 문자열은 그대로 유지한다(웨비나 입장에 반드시 필요).
    """
    parsed = urlparse(url)
    match = ZOOM_JOIN_RE.search(parsed.path)
    if not match:
        return url
    meeting_id = match.group("id")
    path = f"/wc/join/{meeting_id}"
    return urlunparse(parsed._replace(path=path))




# 화면에서 브라우저 내용 영역이 어디인지 '측정' 하기 위한 표식
_CALIBRATION_COLOR = (255, 0, 255)   # 자홍색 - 일반 페이지에 거의 없는 색
_MARKER_JS = """
(show) => {
  const id = '__webrec_calibration__';
  const old = document.getElementById(id);
  if (!show) { if (old) old.remove(); return null; }
  const div = old || document.createElement('div');
  div.id = id;
  div.style.cssText = 'position:fixed;left:0;top:0;width:100vw;height:100vh;' +
                      'background:#ff00ff;z-index:2147483647;pointer-events:none;margin:0';
  if (!old) document.body.appendChild(div);
  return { innerWidth: window.innerWidth, innerHeight: window.innerHeight };
}
"""

# 페이지에서 가장 큰 영상 요소를 찾는다. Zoom 웹클라이언트는 <canvas> 를 쓴다.
_VIDEO_PROBE_JS = """
() => {
  const nodes = Array.from(document.querySelectorAll('video, canvas'));
  let best = null, bestArea = 0;
  for (const el of nodes) {
    const r = el.getBoundingClientRect();
    const area = r.width * r.height;
    const visible = r.width > 120 && r.height > 90 &&
                    getComputedStyle(el).visibility !== 'hidden' &&
                    getComputedStyle(el).display !== 'none';
    if (visible && area > bestArea) { best = el; bestArea = area; }
  }
  if (!best) return null;
  const r = best.getBoundingClientRect();
  return { tag: best.tagName, x: r.x, y: r.y, width: r.width, height: r.height, area: bestArea };
}
"""

# 브라우저 창이 화면 어디에 있는지 (내용 영역의 시작점을 구하는 데 쓴다)
_WINDOW_PROBE_JS = """
() => ({
  screenX: window.screenX, screenY: window.screenY,
  outerWidth: window.outerWidth, outerHeight: window.outerHeight,
  innerWidth: window.innerWidth, innerHeight: window.innerHeight,
  dpr: window.devicePixelRatio || 1,
  screenWidth: window.screen.width, screenHeight: window.screen.height,
})
"""

# 영상 요소를 전체화면으로 만든다(클릭 직후여야 브라우저가 허용한다)
_FULLSCREEN_JS = """
() => {
  const nodes = Array.from(document.querySelectorAll('video, canvas'));
  let best = null, bestArea = 0;
  for (const el of nodes) {
    const r = el.getBoundingClientRect();
    if (r.width * r.height > bestArea) { best = el; bestArea = r.width * r.height; }
  }
  if (!best) return false;
  const target = best.tagName === 'CANVAS' ? (best.parentElement || best) : best;
  const request = target.requestFullscreen || target.webkitRequestFullscreen;
  if (!request) return false;
  try { request.call(target); return true; } catch (e) { return false; }
}
"""



# 영상을 실제로 재생시킨다 (자동재생이 막혀 정지 상태로 녹화되는 것을 막는다)
_PLAY_JS = """
() => {
  const videos = Array.from(document.querySelectorAll('video'));
  if (!videos.length) return { found: false };
  const v = videos.reduce((a, b) => {
    const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
    return (rb.width * rb.height > ra.width * ra.height) ? b : a;
  });
  v.muted = false;
  v.volume = 1;
  const p = v.play();
  if (p && p.catch) p.catch(() => { v.muted = true; v.play().catch(() => {}); });
  return { found: true, paused: v.paused, muted: v.muted, currentTime: v.currentTime };
}
"""

# 재생이 '진행되고 있는지' 확인 (정지 화면인지 아닌지)
_PLAYBACK_STATE_JS = """
() => {
  const videos = Array.from(document.querySelectorAll('video'));
  if (!videos.length) return { found: false };
  const v = videos.reduce((a, b) => {
    const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
    return (rb.width * rb.height > ra.width * ra.height) ? b : a;
  });
  return {
    found: true, paused: v.paused, muted: v.muted, volume: v.volume,
    currentTime: v.currentTime, readyState: v.readyState, ended: v.ended,
  };
}
"""

# 창 테두리 계산에는 1~2픽셀 오차가 있다. 안쪽으로 조금 당겨 페이지 배경이
# 가장자리에 묻어나오지 않게 한다(영상은 거의 손실되지 않는다).
_EDGE_INSET = 3


def _even(value: float) -> int:
    """h264 는 가로/세로가 짝수여야 한다."""
    return max(2, int(round(value)) // 2 * 2)


class BrowserSession:
    """가상 화면 위에 브라우저를 띄우고 사이트에 입장시킨다.

    Playwright 가 설치돼 있으면 클릭/입력 자동화를 하고, 없으면 브라우저를
    kiosk 모드로 실행만 한다(암호 없는 공개 라이브에는 이것으로 충분하다).
    """

    def __init__(self, plan: SitePlan, *, display: str | None, video, browser_cfg):
        self.plan = plan
        self.display = display
        self.video = video
        self.cfg = browser_cfg
        self._playwright = None
        self._browser = None
        self._page = None
        self._proc: subprocess.Popen | None = None
        self.automated = False
        self.notes: list[str] = []      # 참고 사항 (메일/점검 결과에 표시)
        self.warnings: list[str] = []   # 문제 가능성이 있는 사항

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
            }
            if self.display:  # 리눅스 가상 화면. Windows/Mac 은 실제 화면을 쓴다
                launch_kwargs["env"] = {"DISPLAY": self.display}
            executable = self.cfg.executable_path or browser_path()
            if executable:
                launch_kwargs["executable_path"] = executable
            self._browser = self._playwright.chromium.launch(**launch_kwargs)
            context = self._browser.new_context(
                viewport={"width": self.video.width, "height": self.video.height},
                permissions=["camera", "microphone"],
            )
            self._page = context.new_page()
        except Exception as exc:
            log.warning("Playwright 실행 실패(%s) - 기본 브라우저 실행으로 대체합니다.", exc)
            self.close()
            return False

        # 페이지 이동 실패는 '대체 실행' 이 아니라 진짜 오류다.
        # 여기서 넘어가면 브라우저 에러 페이지가 그대로 녹화된다.
        log.info("브라우저 접속: %s", self.plan.launch_url)
        try:
            self._page.goto(self.plan.launch_url, wait_until="domcontentloaded", timeout=60_000)
        except Exception as exc:
            self.close()
            raise CaptureError(f"페이지를 열지 못했습니다: {str(exc).splitlines()[0]}") from exc

        current = (self._page.url or "").lower()
        if current.startswith("chrome-error://"):
            self.close()
            raise CaptureError(f"페이지를 열지 못했습니다(브라우저 오류 화면): {self.plan.launch_url}")
        return True

    def _start_plain(self) -> None:
        executable = browser_path(self.cfg.executable_path)
        if not executable:
            raise CaptureError(
                "브라우저를 찾지 못했습니다. chromium 설치 후 다시 시도하세요 "
                "(sudo apt-get install -y chromium-browser) 또는 WEBREC_BROWSER 환경변수로 경로 지정."
            )
        cmd = [executable] + self._chrome_args() + [self.plan.launch_url]
        log.info("브라우저 실행: %s", executable)
        env = _clean_env()
        if self.display:
            env["DISPLAY"] = self.display
        self._proc = subprocess.Popen(
            cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
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

        if self.cfg.email:
            for selector in ("#input-for-email", "input[name='inputemail']", "input[type='email']"):
                try:
                    box = page.locator(selector).first
                    if box.is_visible(timeout=2_000):
                        box.fill(self.cfg.email)
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

        self._dismiss_banners()
        self.ensure_playing()

    def _dismiss_banners(self) -> None:
        """쿠키/동의 배너를 닫는다. 이게 떠 있으면 재생 버튼을 누를 수 없다."""
        page = self._page
        assert page is not None
        selectors = (
            "button:has-text('Accept all')", "button:has-text('모두 수락')",
            "button:has-text('동의')", "button[aria-label='Accept all']",
            "button[aria-label='모두 수락']", "tp-yt-paper-button:has-text('모두 수락')",
        )
        for selector in selectors:
            try:
                button = page.locator(selector).first
                if button.is_visible(timeout=1_500):
                    button.click(timeout=3_000)
                    page.wait_for_timeout(1_000)
                    return
            except Exception:
                continue

    def ensure_playing(self, *, attempts: int = 4) -> dict:
        """영상이 실제로 재생되도록 만들고, 재생 중인지 확인한다.

        자동재생이 막혀 '정지 화면' 이 그대로 녹화되는 사고를 막는다.
        큰 재생 버튼 클릭 -> JS play() -> 키보드 단축키 순으로 시도하고,
        재생 위치(currentTime)가 실제로 흐르는지까지 확인한다.
        """
        page = self._page
        if page is None:
            return {"found": False}

        for attempt in range(attempts):
            state = self.playback_state()
            if not state.get("found"):
                return state                      # <video> 가 없는 사이트(Zoom 등)
            if state.get("advancing"):
                if state.get("muted"):
                    self.notes.append("영상이 음소거 상태로 재생 중입니다(소리가 녹음되지 않을 수 있습니다).")
                log.info("영상 재생 확인 (위치 %.1fs)", state.get("currentTime", 0))
                return state

            log.info("영상이 멈춰 있어 재생을 시도합니다. (%d/%d)", attempt + 1, attempts)
            self._click_play_button()
            try:
                page.evaluate(_PLAY_JS)
            except Exception as exc:
                log.debug("play() 호출 실패: %s", exc)
            if attempt >= 1:
                for key in ("k", "Space"):
                    try:
                        page.keyboard.press(key)
                        page.wait_for_timeout(400)
                    except Exception:
                        pass
            page.wait_for_timeout(1_200)

        final = self.playback_state()
        if final.get("found") and not final.get("advancing"):
            message = "영상이 재생되지 않고 정지 상태입니다(재생 버튼을 누르지 못했습니다)."
            log.warning(message)
            self.warnings.append({"name": "재생 상태", "detail": message})
        return final

    def _click_play_button(self) -> None:
        """사이트별 큰 재생 버튼을 눌러 본다."""
        page = self._page
        assert page is not None
        selectors = (
            ".ytp-large-play-button",           # YouTube 가운데 큰 버튼
            "button.ytp-play-button",           # YouTube 하단 재생 버튼
            "button[aria-label*='재생']",
            "button[aria-label*='Play']",
            "button[title*='Play']",
            ".vjs-big-play-button",             # video.js
            ".plyr__control--overlaid",         # Plyr
            "video",                            # 마지막 수단: 영상 자체 클릭
        )
        for selector in selectors:
            try:
                element = page.locator(selector).first
                if element.count() and element.is_visible(timeout=1_200):
                    element.click(timeout=3_000, force=True)
                    page.wait_for_timeout(600)
                    return
            except Exception:
                continue

    def playback_state(self) -> dict:
        """재생 상태를 확인한다. 재생 위치가 흐르는지(advancing)까지 본다."""
        page = self._page
        if page is None:
            return {"found": False}
        try:
            first = page.evaluate(_PLAYBACK_STATE_JS)
            if not first or not first.get("found"):
                return {"found": False}
            page.wait_for_timeout(1_200)
            second = page.evaluate(_PLAYBACK_STATE_JS)
            advancing = bool(
                second and second.get("found")
                and not second.get("paused")
                and second.get("currentTime", 0) > first.get("currentTime", 0)
            )
            state = dict(second or first)
            state["advancing"] = advancing
            return state
        except Exception as exc:
            log.debug("재생 상태 확인 실패: %s", exc)
            return {"found": False}

    # -------------------------------------------------------------- 녹화 영역
    def capture_region(self) -> tuple[int, int, int, int] | None:
        """녹화할 화면 영역을 정한다. 실패하면 None(전체 화면)."""
        try:
            region = self._capture_region()
        except Exception as exc:  # 영역 계산 실패로 녹화를 못 하면 안 된다
            log.warning("녹화 영역을 정하지 못해 화면 전체를 녹화합니다: %s", exc)
            return None
        if region is None:
            return None
        if not isinstance(region, (tuple, list)) or len(region) != 4:
            log.warning("녹화 영역 값이 올바르지 않아 화면 전체를 녹화합니다: %r", region)
            return None
        return tuple(int(value) for value in region)  # type: ignore[return-value]

    def _capture_region(self) -> tuple[int, int, int, int] | None:
        """녹화할 화면 영역을 정한다.

        반환값이 None 이면 화면 전체를 녹화한다.
        설정(capture)에 따라:
          screen - 항상 전체 화면
          region - 사용자가 지정한 좌표
          video  - 영상 요소 위치를 계산해 그 부분만
          auto   - 영상을 전체화면으로 만들어 보고(화질이 가장 좋다),
                   안 되면 영상 요소 위치만큼 잘라낸다
        """
        mode = (getattr(self.cfg, "capture", "auto") or "auto").lower()

        if mode == "screen":
            return None
        if mode == "region":
            return _parse_region(getattr(self.cfg, "region", None))
        if not self.automated or self._page is None:
            if mode == "video":
                log.warning(
                    "영상 영역만 녹화하려면 playwright 가 필요합니다. 전체 화면을 녹화합니다."
                )
            return None

        if mode == "auto" and self._make_video_fullscreen():
            log.info("영상을 전체화면으로 만들었습니다. 화면 전체를 녹화합니다(=영상만).")
            return None

        rect = self._video_screen_rect()
        if rect is None:
            log.warning("페이지에서 영상 영역을 찾지 못해 화면 전체를 녹화합니다.")
        else:
            log.info("영상 영역만 녹화합니다: %dx%d (위치 %d,%d)", rect[2], rect[3], rect[0], rect[1])
        return rect

    def _make_video_fullscreen(self) -> bool:
        """영상 요소를 전체화면으로. 성공하면 True."""
        page = self._page
        assert page is not None
        try:
            # 전체화면 요청은 '사용자 조작 직후' 에만 허용되므로 먼저 클릭한다
            element = page.locator("video, canvas").first
            if element.count() == 0:
                return False
            try:
                element.click(timeout=3_000, force=True)
            except Exception:
                pass
            if not page.evaluate(_FULLSCREEN_JS):
                return False
            page.wait_for_timeout(1_500)

            # 정말 화면을 채웠는지 확인한다
            info = page.evaluate(_WINDOW_PROBE_JS)
            video = page.evaluate(_VIDEO_PROBE_JS)
            if not video or not info:
                return False
            covered = (video["width"] * video["height"]) / max(
                1, info["screenWidth"] * info["screenHeight"]
            )
            return covered >= 0.8
        except Exception as exc:
            log.debug("전체화면 전환 실패: %s", exc)
            return False

    def _measure_viewport(self) -> tuple[float, float, float] | None:
        """브라우저 내용 영역이 화면 어디에서 시작하는지 직접 측정한다.

        페이지 전체를 덮는 자홍색 표식을 잠깐 띄우고 화면을 한 장 찍어
        그 표식이 실제로 찍힌 위치를 읽는다. 창 관리자 유무·화면 배율·
        전체화면 여부와 상관없이 정확하다.

        반환: (화면상 x, 화면상 y, 배율). 배율은 CSS 픽셀 -> 화면 픽셀 비율.
        """
        page = self._page
        assert page is not None
        info = None
        box = None
        try:
            info = page.evaluate(_MARKER_JS, True)
            if info:
                page.wait_for_timeout(250)
                screen_info = page.evaluate(_WINDOW_PROBE_JS)
                dpr = screen_info.get("dpr") or 1
                width = int(screen_info["screenWidth"] * dpr)
                height = int(screen_info["screenHeight"] * dpr)
                frame = grab_frame(display=self.display, width=width, height=height)
                if frame:
                    box = find_color_box(frame, width, height, _CALIBRATION_COLOR)
        except Exception as exc:
            log.debug("내용 영역 측정 실패: %s", exc)
        finally:
            try:
                page.evaluate(_MARKER_JS, False)
            except Exception:
                pass

        if not box or not info:
            return None

        x, y, measured_width, _ = box
        scale = measured_width / max(1, info["innerWidth"])
        if not (0.3 <= scale <= 4.0):      # 측정값이 이상하면 쓰지 않는다
            log.debug("측정된 배율이 이상합니다: %.2f", scale)
            return None
        log.debug("내용 영역 측정: 시작(%d,%d) 배율 %.2f", x, y, scale)
        return float(x), float(y), float(scale)

    def _video_screen_rect(self) -> tuple[int, int, int, int] | None:
        """영상 요소가 화면 좌표로 어디에 있는지 구한다."""
        page = self._page
        assert page is not None
        try:
            info = page.evaluate(_WINDOW_PROBE_JS)
        except Exception:
            return None

        best = None
        for frame in page.frames:
            try:
                found = frame.evaluate(_VIDEO_PROBE_JS)
            except Exception:
                continue
            if not found:
                continue
            if frame != page.main_frame:  # iframe 안이면 iframe 위치를 더해준다
                try:
                    box = frame.frame_element().bounding_box()
                except Exception:
                    box = None
                if not box:
                    continue
                found["x"] += box["x"]
                found["y"] += box["y"]
            if best is None or found["area"] > best["area"]:
                best = found

        if not best:
            return None

        measured = self._measure_viewport()
        if measured:
            origin_x, origin_y, scale = measured          # 실제로 측정한 값
        else:
            # 측정에 실패하면 창 정보로 계산한다(환경에 따라 몇 픽셀 어긋날 수 있다)
            log.debug("내용 영역을 측정하지 못해 창 정보로 계산합니다.")
            border = max(0, (info["outerWidth"] - info["innerWidth"]) / 2)
            top_bar = max(0, info["outerHeight"] - info["innerHeight"] - border)
            scale = info.get("dpr") or 1
            origin_x = (info["screenX"] + border) * scale
            origin_y = (info["screenY"] + top_bar) * scale

        x = origin_x + best["x"] * scale
        y = origin_y + best["y"] * scale
        width = best["width"] * scale
        height = best["height"] * scale
        dpr = scale

        # 화면 밖으로 나가지 않게 자른다
        screen_w = info["screenWidth"] * dpr
        screen_h = info["screenHeight"] * dpr
        x = max(0, min(x, screen_w - 2))
        y = max(0, min(y, screen_h - 2))
        width = min(width, screen_w - x)
        height = min(height, screen_h - y)
        if width < 100 or height < 100:
            return None

        # 가장자리에 페이지 배경이 1~2픽셀 묻어나오는 것을 막는다
        inset = _EDGE_INSET if width > 4 * _EDGE_INSET and height > 4 * _EDGE_INSET else 0
        return (
            int(x) + inset,
            int(y) + inset,
            _even(width - 2 * inset),
            _even(height - 2 * inset),
        )

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


def _parse_region(text: str | None) -> tuple[int, int, int, int] | None:
    """'x,y,너비,높이' 문자열을 좌표로 바꾼다."""
    if not text:
        return None
    parts = [piece.strip() for piece in str(text).replace("x", ",").split(",") if piece.strip()]
    if len(parts) != 4:
        log.warning("녹화 영역 형식이 잘못되었습니다(x,y,너비,높이): %s", text)
        return None
    try:
        x, y, width, height = (int(float(piece)) for piece in parts)
    except ValueError:
        log.warning("녹화 영역에 숫자가 아닌 값이 있습니다: %s", text)
        return None
    return max(0, x), max(0, y), _even(width), _even(height)
