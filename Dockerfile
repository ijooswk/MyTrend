# MyTrend — 단일 컨테이너 (FastAPI API + 정적 프론트엔드)
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    MYTREND_DB_PATH=/app/data/mytrend.db

# curl: 헬스체크용. (kiwipiepy 는 manylinux/arm64 휠로 설치됨)
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 의존성 먼저 설치(레이어 캐시 활용)
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install -r /app/backend/requirements.txt

# 애플리케이션 코드
COPY backend /app/backend
COPY frontend /app/frontend

# DB 영속 디렉터리
RUN mkdir -p /app/data

WORKDIR /app/backend
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
