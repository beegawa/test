#!/usr/bin/env bash
# =============================================================================
#  webrec 서버 설치 - 우분투/데비안 서버에서 한 번만 실행
#
#    bash deploy/setup-server.sh
#
#  끝나면 systemd 서비스로 24시간 떠 있고, 재부팅해도 자동으로 살아납니다.
# =============================================================================
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_USER="${WEBREC_USER:-$(id -un)}"
PORT="${WEBREC_PORT:-8765}"
BIND="${WEBREC_BIND:-127.0.0.1}"
SUDO=""
[ "$(id -u)" -ne 0 ] && SUDO="sudo"

echo "설치 위치: $APP_DIR"
echo "실행 계정: $SERVICE_USER"
echo

echo "[1/5] 시스템 패키지 설치"
export DEBIAN_FRONTEND=noninteractive
$SUDO apt-get update -qq
$SUDO apt-get install -y --no-install-recommends \
  ffmpeg xvfb pulseaudio pulseaudio-utils \
  python3 python3-pip python3-venv \
  fonts-noto-cjk ca-certificates

echo "[2/5] 파이썬 환경 준비"
if [ ! -d "$APP_DIR/.venv" ]; then
  python3 -m venv "$APP_DIR/.venv"
fi
"$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

echo "[3/5] 브라우저 설치 (Zoom 등 화면 캡처용)"
# 서버에는 데스크톱 브라우저가 없다. playwright 로 받아보고, 막히면 apt 로 대체한다.
# 브라우저가 없어도 스트림 녹화(YouTube 등)는 되므로 실패해도 설치를 계속한다.
BROWSER_OK=0
$SUDO "$APP_DIR/.venv/bin/playwright" install-deps chromium >/dev/null 2>&1 || \
  echo "  (브라우저 의존 패키지 설치 생략)"
if "$APP_DIR/.venv/bin/playwright" install chromium >/dev/null 2>&1; then
  BROWSER_OK=1
  echo "  playwright 크로뮴 설치 완료"
else
  echo "  playwright 내려받기 실패(방화벽?) - apt 로 시도합니다"
  if $SUDO apt-get install -y --no-install-recommends chromium >/dev/null 2>&1 || \
     $SUDO apt-get install -y --no-install-recommends chromium-browser >/dev/null 2>&1; then
    BROWSER_OK=1
    echo "  apt 크로뮴 설치 완료"
  else
    echo "  !! 브라우저를 설치하지 못했습니다."
    echo "     Zoom 같은 '브라우저 화면 캡처' 는 쓸 수 없고,"
    echo "     YouTube 등 '스트림 녹화' 만 동작합니다."
  fi
fi

echo "[4/5] systemd 서비스 등록"
if ! command -v systemctl >/dev/null 2>&1 || ! [ -d /run/systemd/system ]; then
  cat <<NOSYSTEMD

  이 시스템에는 systemd 가 없습니다(도커 컨테이너 등).
  서비스 등록을 건너뜁니다. 아래 명령으로 직접 실행하세요:

    $APP_DIR/.venv/bin/python -m webrec serve --host $BIND --port $PORT \
      --out $APP_DIR/recordings --data-dir $APP_DIR/.webrec --log-dir $APP_DIR/logs

NOSYSTEMD
  exit 0
fi

$SUDO tee /etc/systemd/system/webrec.service >/dev/null <<UNIT
[Unit]
Description=webrec - 예약 웹 라이브 녹화
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$APP_DIR
Environment=HOME=/home/$SERVICE_USER
EnvironmentFile=-$APP_DIR/.env
ExecStart=$APP_DIR/.venv/bin/python -m webrec serve --host $BIND --port $PORT \\
          --out $APP_DIR/recordings --data-dir $APP_DIR/.webrec --log-dir $APP_DIR/logs
Restart=always
RestartSec=10
KillSignal=SIGTERM
TimeoutStopSec=600

[Install]
WantedBy=multi-user.target
UNIT

$SUDO systemctl daemon-reload
$SUDO systemctl enable --now webrec

echo "[5/5] 상태 확인"
sleep 2
"$APP_DIR/.venv/bin/python" -m webrec doctor || true
echo
$SUDO systemctl --no-pager --lines=5 status webrec || true

cat <<MSG

======================================================================
 설치 완료

 웹 화면은 보안을 위해 서버 내부(127.0.0.1)에서만 열려 있습니다.
 내 PC 에서 아래처럼 터널을 뚫고 접속하세요:

   ssh -L ${PORT}:127.0.0.1:${PORT} 사용자@서버주소
   → 브라우저에서 http://127.0.0.1:${PORT}

 상태 보기 :  sudo systemctl status webrec
 로그 보기 :  sudo journalctl -u webrec -f
 다시 시작 :  sudo systemctl restart webrec

 ※ 인터넷에 그대로 여는 것(--host 0.0.0.0)은 권장하지 않습니다.
   예약 목록과 녹화 파일이 누구에게나 보입니다.
======================================================================
MSG
