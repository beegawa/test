#!/usr/bin/env bash
# webrec 실행에 필요한 시스템 패키지 설치 (Debian/Ubuntu 기준)
set -euo pipefail

SUDO=""
if [ "$(id -u)" -ne 0 ]; then SUDO="sudo"; fi

echo "[1/3] 시스템 패키지 설치 (ffmpeg / Xvfb / PulseAudio / Chromium)"
$SUDO apt-get update
$SUDO apt-get install -y --no-install-recommends \
  ffmpeg \
  xvfb \
  pulseaudio \
  chromium-browser || \
$SUDO apt-get install -y --no-install-recommends ffmpeg xvfb pulseaudio chromium

echo "[2/3] 파이썬 패키지 설치"
python3 -m pip install --upgrade pip
python3 -m pip install -r "$(dirname "$0")/../requirements.txt"

echo "[3/3] Playwright 브라우저 설치 (브라우저 캡처용, 실패해도 무방)"
python3 -m playwright install chromium || echo "  건너뜀: 시스템 chromium 을 사용합니다."

echo
echo "설치 완료. 확인: python3 -m webrec doctor"
