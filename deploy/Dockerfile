# =============================================================================
#  webrec 컨테이너 이미지
#   - 서버(VM)에서:      docker compose -f deploy/docker-compose.yml up -d
#   - Cloud Run Job 에서: 명령을 'once' 로 바꿔 한 번 녹화하고 종료
#  프로젝트 최상위에서 빌드하세요:  docker build -f deploy/Dockerfile -t webrec .
# =============================================================================
FROM python:3.12-slim-bookworm

# 녹화 엔진(ffmpeg), 가상 화면(Xvfb), 소리(PulseAudio), 브라우저(Chromium),
# 한글 폰트(화면 캡처에 한글이 깨지지 않도록)
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        xvfb \
        pulseaudio pulseaudio-utils \
        chromium \
        fonts-noto-cjk \
        tini \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ENV WEBREC_BROWSER=/usr/bin/chromium \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt ./
# playwright 브라우저는 위에서 apt 로 깐 chromium 을 쓰므로 따로 받지 않는다
RUN pip install --no-cache-dir -r requirements.txt

COPY webrec ./webrec
COPY pyproject.toml README.md ./

# 녹화물·예약·로그는 모두 /data 아래에 둔다 (볼륨으로 빼기 쉽게)
VOLUME ["/data"]
EXPOSE 8765

# tini 가 있어야 ffmpeg/브라우저 자식 프로세스가 좀비로 남지 않는다
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "webrec", "serve", \
     "--host", "0.0.0.0", "--port", "8765", \
     "--out", "/data/recordings", "--data-dir", "/data/state", "--log-dir", "/data/logs"]
