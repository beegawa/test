#!/bin/bash
# macOS/Linux 실행 스크립트 - 더블클릭하거나 `bash start_mac.command` 로 실행
cd "$(dirname "$0")" || exit 1

echo
echo "  회사 ChatGPT 대화 로그 콘솔"
echo "  ------------------------------------------------"

PY=python3
command -v "$PY" >/dev/null 2>&1 || { echo "  파이썬 3.10 이상이 필요합니다."; exit 1; }
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' || {
  echo "  파이썬 3.10 이상이 필요합니다. 현재: $($PY -V)"; exit 1; }

echo "  [1/2] 필요한 패키지 확인"
"$PY" -m pip install --quiet --disable-pip-version-check -r requirements.txt || {
  echo "  패키지 설치에 실패했습니다."; exit 1; }

echo "  [2/2] 웹 콘솔 시작 - 브라우저가 자동으로 열립니다"
echo
exec "$PY" app.py
