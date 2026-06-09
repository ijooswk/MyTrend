#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# MyTrend 로컬 관리 스크립트 (Docker)
#   사용법: ./manage.sh <command>
# ──────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")"

PORT="${MYTREND_PORT:-8000}"

# docker compose v2 / v1 자동 감지
if docker compose version >/dev/null 2>&1; then
  DC="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  DC="docker-compose"
else
  echo "❌ docker compose 를 찾을 수 없습니다. Docker 를 설치하세요."; exit 1
fi

# 최초 실행 시 .env 준비
ensure_env() {
  if [ ! -f .env ]; then
    cp .env.example .env
    echo "ℹ .env 생성됨 — 필요하면 API 키를 채우세요."
  fi
}

usage() {
  cat <<EOF
MyTrend 관리 명령:
  ./manage.sh build      이미지 빌드
  ./manage.sh up         빌드 후 백그라운드 기동
  ./manage.sh down       중지 및 컨테이너 제거
  ./manage.sh restart    재시작
  ./manage.sh logs       로그 팔로우 (Ctrl-C 종료)
  ./manage.sh status     컨테이너/헬스 상태
  ./manage.sh ingest     수동 즉시 수집 트리거
  ./manage.sh stats      DB/스케줄러 상태 조회
  ./manage.sh shell      백엔드 컨테이너 셸 진입
  ./manage.sh psql       PostgreSQL 셸(psql) 진입
  ./manage.sh backup     DB 덤프를 ./mytrend-backup-<날짜>.sql 로 저장
  ./manage.sh clean      컨테이너+볼륨(DB)까지 삭제
  ./manage.sh open       브라우저로 열기
EOF
}

cmd="${1:-help}"
case "$cmd" in
  build)   ensure_env; $DC build ;;
  up)      ensure_env; $DC up -d --build
           echo "✅ http://localhost:${PORT} 에서 실행 중" ;;
  down)    $DC down ;;
  restart) $DC restart ;;
  logs)    $DC logs -f --tail=100 ;;
  status)  $DC ps
           echo "--- health ---"
           curl -fsS "http://localhost:${PORT}/api/health" && echo || echo "(응답 없음)" ;;
  ingest)  echo "수집 트리거…"
           curl -fsS -X POST "http://localhost:${PORT}/api/ingest" | sed 's/,/,\n/g' ;;
  stats)   curl -fsS "http://localhost:${PORT}/api/stats" ;;
  shell)   $DC exec backend /bin/bash || $DC exec backend /bin/sh ;;
  psql)    $DC exec db psql -U "${POSTGRES_USER:-mytrend}" -d "${POSTGRES_DB:-mytrend}" ;;
  backup)  OUT="mytrend-backup-$(date +%F).sql"
           $DC exec -T db pg_dump -U "${POSTGRES_USER:-mytrend}" "${POSTGRES_DB:-mytrend}" > "$OUT"
           echo "💾 저장됨: $OUT" ;;
  clean)   $DC down -v; echo "🗑  컨테이너 및 볼륨(DB) 삭제 완료" ;;
  open)    URL="http://localhost:${PORT}"
           (command -v open >/dev/null && open "$URL") || \
           (command -v xdg-open >/dev/null && xdg-open "$URL") || echo "$URL" ;;
  help|-h|--help) usage ;;
  *) echo "알 수 없는 명령: $cmd"; echo; usage; exit 1 ;;
esac
