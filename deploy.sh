#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# MyTrend — 원격 서버 배포 스크립트  (quantum-invest 배포 패턴 참고)
#
#   1) 로컬 소스를 rsync 로 서버에 동기화 (.git/.venv/__pycache__/*.db 등 제외)
#   2) 서버에서 docker compose 로 빌드 & 기동 (2컨테이너: nginx 프론트 + uvicorn 백엔드)
#   3) /api/health 헬스체크
#
# 사용법:
#   ./deploy.sh                 # 동기화 + 빌드 + 기동
#   ./deploy.sh --no-build      # 동기화 후 재기동만 (이미지 재빌드 생략)
#   ./deploy.sh --logs          # 배포 후 로그 따라보기
#
# 설정/자격증명은 같은 폴더의 deploy.env(gitignore) 에서 읽습니다.
# (권장: `ssh-copy-id sehun@100.98.178.217` 로 키 등록 → SERVER_PASSWORD 불필요)
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

# ── 설정 로드 (deploy.env → 환경변수 → 기본값) ─────────────────────────────────
[ -f deploy.env ] && { set -a; . ./deploy.env; set +a; }
SERVER_IP="${SERVER_IP:-100.98.178.217}"
SERVER_USER="${SERVER_USER:-sehun}"
SERVER_PASSWORD="${SERVER_PASSWORD:-}"
SSH_PORT="${SSH_PORT:-22}"
REMOTE_DIR="${REMOTE_DIR:-/home/${SERVER_USER}/mytrend}"
COMPOSE_FILE="docker-compose.prod.yml"

# ── 옵션 ───────────────────────────────────────────────────────────────────────
DO_BUILD=1; FOLLOW_LOGS=0
for arg in "$@"; do
  case "$arg" in
    --no-build) DO_BUILD=0 ;;
    --logs)     FOLLOW_LOGS=1 ;;
    *) echo "알 수 없는 옵션: $arg"; exit 1 ;;
  esac
done

# ── sshpass 래퍼 (SSH 키가 있으면 자동으로 비밀번호 없이 동작) ──────────────────
SSH_OPTS=(-o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 -p "${SSH_PORT}")
if [ -n "${SERVER_PASSWORD}" ] && command -v sshpass >/dev/null 2>&1; then
  SSHPASS_PREFIX=(sshpass -p "${SERVER_PASSWORD}")
else
  SSHPASS_PREFIX=()
  [ -n "${SERVER_PASSWORD}" ] && echo "ⓘ sshpass 가 없어 SSH 키 인증을 시도합니다. (brew install hudochenkov/sshpass/sshpass)"
fi
run_ssh() { "${SSHPASS_PREFIX[@]}" ssh "${SSH_OPTS[@]}" "${SERVER_USER}@${SERVER_IP}" "$@"; }

echo "==> 대상 서버: ${SERVER_USER}@${SERVER_IP}:${REMOTE_DIR}"

# ── 0. 사전 점검: 접속 & Docker ─────────────────────────────────────────────────
echo "==> [0/4] SSH 접속 및 Docker 확인"
run_ssh "mkdir -p '${REMOTE_DIR}' && echo OK" >/dev/null
if ! run_ssh "command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1"; then
  echo "‼  서버에 Docker / docker compose 가 없습니다. 서버에서 먼저 실행하세요:"
  echo "     curl -fsSL https://get.docker.com | sh"
  echo "     sudo usermod -aG docker ${SERVER_USER}   # 재로그인 필요"
  exit 1
fi

# ── 1. 소스 동기화 (rsync) ──────────────────────────────────────────────────────
echo "==> [1/4] 소스 동기화 (rsync)"
RSYNC_RSH="${SSHPASS_PREFIX[*]:+sshpass -p ${SERVER_PASSWORD} }ssh -o StrictHostKeyChecking=accept-new -p ${SSH_PORT}"
# 주의: '/.env' 처럼 슬래시로 앵커해야 루트 .env 만 제외되고 backend/.env(API 키)는 전송됨.
rsync -az --delete \
  -e "${RSYNC_RSH}" \
  --exclude '.git' \
  --exclude 'backend/.venv' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude '.pytest_cache' \
  --exclude '*.db' \
  --exclude '/data' \
  --exclude '/.env' \
  --exclude '/deploy.env' \
  --exclude '*.log' \
  --exclude '.DS_Store' \
  --exclude 'outputs' \
  "${SCRIPT_DIR}/" "${SERVER_USER}@${SERVER_IP}:${REMOTE_DIR}/"

# ── 2. 환경변수 파일 준비 ───────────────────────────────────────────────────────
echo "==> [2/4] 환경변수(.env) 확인"
run_ssh "cd '${REMOTE_DIR}' && \
  if [ ! -f .env ]; then cp .env.prod.example .env && echo '⚠  .env 를 .env.prod.example 에서 생성했습니다(기본 포트 19090).'; \
  else echo '.env 존재 — 그대로 사용'; fi && \
  if [ ! -f backend/.env ]; then echo '‼  backend/.env (API 키) 가 서버에 없습니다 — EODHD/OpenRouter/Tavily 키를 설정하세요.'; fi"

# ── 3. 빌드 & 기동 ──────────────────────────────────────────────────────────────
echo "==> [3/4] docker compose 기동"
BUILD_FLAG=""; [ "${DO_BUILD}" -eq 1 ] && BUILD_FLAG="--build"
run_ssh "cd '${REMOTE_DIR}' && docker compose -f ${COMPOSE_FILE} up -d --remove-orphans ${BUILD_FLAG}"

# ── 4. 헬스체크 ─────────────────────────────────────────────────────────────────
echo "==> [4/4] 헬스체크 (최대 60초 대기)"
PORT="$(run_ssh "cd '${REMOTE_DIR}' && (grep -E '^MYTREND_PORT=' .env 2>/dev/null | cut -d= -f2)" || true)"
PORT="${PORT:-19090}"
HEALTH_OK=0
for i in $(seq 1 12); do
  if run_ssh "curl -fsS http://localhost:${PORT}/api/health >/dev/null 2>&1"; then HEALTH_OK=1; break; fi
  sleep 5
done

echo ""
if [ "${HEALTH_OK}" -eq 1 ]; then
  echo "✅ 배포 완료 — 정상 동작"
else
  echo "⚠  헬스체크 실패. 로그를 확인하세요:"
  echo "    ssh ${SERVER_USER}@${SERVER_IP} 'cd ${REMOTE_DIR} && docker compose -f ${COMPOSE_FILE} logs --tail=80'"
fi
run_ssh "cd '${REMOTE_DIR}' && docker compose -f ${COMPOSE_FILE} ps" || true

echo ""
echo "   앱(프론트+API): http://${SERVER_IP}:${PORT}"
echo "   API 문서:        http://${SERVER_IP}:${PORT}/docs"
echo "   최초 1회 롤업:   curl -X POST http://${SERVER_IP}:${PORT}/api/rollup"

if [ "${FOLLOW_LOGS}" -eq 1 ]; then
  echo "==> 로그 follow (Ctrl-C 로 종료)"
  run_ssh "cd '${REMOTE_DIR}' && docker compose -f ${COMPOSE_FILE} logs -f --tail=50"
fi
