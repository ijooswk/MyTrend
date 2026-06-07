#!/usr/bin/env bash
# MyTrend 백엔드 실행 스크립트
set -e
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "▶ 가상환경 생성..."
  python3 -m venv .venv
fi
source .venv/bin/activate

echo "▶ 의존성 설치..."
pip install -q -r requirements.txt

if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "ℹ .env 생성됨 — API 키를 채우면 Tavily/EODHD/NewsAPI 소스가 활성화됩니다."
fi

echo "▶ 서버 시작: http://localhost:8000"
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
