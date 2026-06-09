# MyTrend 백엔드 이미지 — FastAPI(uvicorn) API 전용 (정적 프론트엔드 미포함).
#   build context: ./backend
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    MYTREND_DB_PATH=/app/data/mytrend.db

# curl: 헬스체크용. (kiwipiepy 는 manylinux/arm64 휠로 설치됨)
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 의존성 먼저(레이어 캐시)
COPY requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

# 애플리케이션 코드 (frontend 는 별도 nginx 이미지가 서빙)
COPY . /app/backend

# SQLite 영속 디렉터리
RUN mkdir -p /app/data

WORKDIR /app/backend
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://localhost:${MYTREND_BIND_PORT:-8000}/api/health" || exit 1

CMD ["sh", "-c", "uvicorn app.main:app --host ${MYTREND_BIND_HOST:-0.0.0.0} --port ${MYTREND_BIND_PORT:-8000}"]
