#!/usr/bin/env bash
# n8n 설치 + 뉴스 클리핑 워크플로우 등록 (macOS / Linux)
set -euo pipefail
BASE="${N8N_BASE:-$HOME/n8n}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "[1/4] Node.js 확인"
if ! command -v node >/dev/null 2>&1; then
  echo "  Node.js 가 없습니다. 설치를 시작합니다..."
  if command -v brew >/dev/null 2>&1; then
    brew install node@22
  elif command -v apt-get >/dev/null 2>&1; then
    curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
    sudo apt-get install -y nodejs
  else
    echo "  자동 설치 불가. https://nodejs.org 에서 LTS 를 설치한 뒤 다시 실행하세요." >&2
    exit 1
  fi
fi
NODE_MAJOR=$(node -p "process.versions.node.split('.')[0]")
if [ "$NODE_MAJOR" -lt 20 ]; then
  echo "  Node.js 20 이상이 필요합니다 (현재 $(node -v))." >&2; exit 1
fi
echo "  Node.js $(node -v)"

echo "[2/4] n8n 설치 (수 분 소요)"
npm install -g n8n
echo "  설치 완료"

echo "[3/4] 실행 환경 구성"
mkdir -p "$BASE/data" "$BASE/files" "$BASE/logs"
chmod 700 "$BASE/data"
if [ ! -f "$BASE/.env" ]; then
  cat > "$BASE/.env" <<EOF
N8N_USER_FOLDER=$BASE/data
N8N_LISTEN_ADDRESS=127.0.0.1
N8N_PORT=5678
GENERIC_TIMEZONE=Asia/Seoul
TZ=Asia/Seoul
N8N_ENCRYPTION_KEY=$(openssl rand -hex 32)
N8N_DEFAULT_BINARY_DATA_MODE=filesystem
N8N_DIAGNOSTICS_ENABLED=false
N8N_VERSION_NOTIFICATIONS_ENABLED=false
N8N_RESTRICT_FILE_ACCESS_TO=$BASE/files
EXECUTIONS_DATA_PRUNE=true
EXECUTIONS_DATA_MAX_AGE=720
EOF
  chmod 600 "$BASE/.env"
  echo "  설정 파일 생성: $BASE/.env"
else
  echo "  기존 설정 유지: $BASE/.env"
fi

set -a; source "$BASE/.env"; set +a

echo "[4/4] 워크플로우 등록"
n8n import:workflow --input="$HERE/workflows/daily-news-clipping.json"

echo
echo "완료. 아래 명령으로 n8n 을 실행하세요:"
echo "  set -a; source $BASE/.env; set +a; n8n start"
echo "실행 후 브라우저에서 http://localhost:5678 접속"
