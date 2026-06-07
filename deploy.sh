#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# MyTrend 원격 배포 스크립트
#   로컬 소스를 원격 서버로 전송 → 원격 Docker 에서 빌드/기동.
#   사용법: ./deploy.sh [up|down|logs|status|restart]   (기본: up)
#   설정/자격증명: deploy.env  (deploy.env.example 참고)
# ──────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")"

# ── 설정 로드 ──
if [ -f deploy.env ]; then
  set -a; . ./deploy.env; set +a
else
  echo "❌ deploy.env 가 없습니다. 'cp deploy.env.example deploy.env' 후 값을 채우세요."; exit 1
fi
: "${REMOTE_HOST:?REMOTE_HOST 미설정}"
: "${REMOTE_USER:?REMOTE_USER 미설정}"
REMOTE_PORT="${REMOTE_PORT:-22}"
REMOTE_DIR="${REMOTE_DIR:-~/mytrend}"
MYTREND_PORT="${MYTREND_PORT:-8000}"
ACTION="${1:-up}"

# ── SSH/SCP 래퍼 (키 우선, 없으면 sshpass 비밀번호) ──
SSH_OPTS="-o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 -p ${REMOTE_PORT}"
RSYNC_SSH="ssh -o StrictHostKeyChecking=accept-new -p ${REMOTE_PORT}"
SSHPASS_PREFIX=()
if [ -n "${REMOTE_PASS:-}" ]; then
  if ! command -v sshpass >/dev/null 2>&1; then
    echo "❌ REMOTE_PASS 가 설정됐지만 sshpass 가 없습니다."
    echo "   설치: macOS 'brew install hudochenkov/sshpass/sshpass' / Ubuntu 'sudo apt install sshpass'"
    echo "   또는 SSH 키를 설정하고 deploy.env 의 REMOTE_PASS 를 비우세요."
    exit 1
  fi
  SSHPASS_PREFIX=(sshpass -p "${REMOTE_PASS}")
  RSYNC_SSH="sshpass -p ${REMOTE_PASS} ssh -o StrictHostKeyChecking=accept-new -p ${REMOTE_PORT}"
fi

rexec() { "${SSHPASS_PREFIX[@]}" ssh ${SSH_OPTS} "${REMOTE_USER}@${REMOTE_HOST}" "$@"; }

# ── 원격 docker compose 명령 감지 ──
remote_dc() {
  rexec 'if docker compose version >/dev/null 2>&1; then echo "docker compose"; \
         elif command -v docker-compose >/dev/null 2>&1; then echo "docker-compose"; \
         else echo "NONE"; fi'
}

check_prereqs() {
  echo "▶ 원격 환경 점검 (${REMOTE_USER}@${REMOTE_HOST})…"
  if ! rexec 'command -v docker >/dev/null 2>&1'; then
    echo "❌ 원격에 docker 가 없습니다. 먼저 Docker 를 설치하세요."; exit 1
  fi
  DC="$(remote_dc)"
  if [ "$DC" = "NONE" ]; then
    echo "❌ 원격에 docker compose 플러그인이 없습니다 (docker-compose-plugin 설치 필요)."; exit 1
  fi
  echo "  docker OK · compose: ${DC}"
}

sync_files() {
  echo "▶ 소스 전송 → ${REMOTE_DIR}"
  rexec "mkdir -p ${REMOTE_DIR}"
  if command -v rsync >/dev/null 2>&1; then
    rsync -az --delete \
      --exclude '.git' --exclude '__pycache__' --exclude '*.pyc' \
      --exclude 'backend/.venv' --exclude '*.db' --exclude 'data' \
      --exclude 'deploy.env' --exclude '*.log' \
      -e "${RSYNC_SSH}" ./ "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}/"
  else
    echo "  (rsync 없음 → tar+scp 폴백)"
    tar czf - --exclude='.git' --exclude='__pycache__' --exclude='*.pyc' \
      --exclude='backend/.venv' --exclude='*.db' --exclude='data' \
      --exclude='deploy.env' . | rexec "mkdir -p ${REMOTE_DIR} && tar xzf - -C ${REMOTE_DIR}"
  fi
  # 포트 설정 주입(.env 없으면 생성)
  rexec "cd ${REMOTE_DIR} && [ -f .env ] || cp .env.example .env; \
         sed -i 's/^MYTREND_PORT=.*/MYTREND_PORT=${MYTREND_PORT}/' .env || true"
}

remote_compose() {
  local DC; DC="$(remote_dc)"
  rexec "cd ${REMOTE_DIR} && ${DC} $*"
}

case "$ACTION" in
  up)
    check_prereqs
    sync_files
    echo "▶ 원격 빌드 및 기동…"
    remote_compose "up -d --build"
    echo "▶ 상태:"
    remote_compose "ps" || true
    echo "✅ 배포 완료 → http://${REMOTE_HOST}:${MYTREND_PORT}"
    ;;
  down)    check_prereqs; remote_compose "down"; echo "✅ 원격 중지" ;;
  restart) check_prereqs; remote_compose "restart"; echo "✅ 재시작" ;;
  status)  check_prereqs; remote_compose "ps"
           rexec "curl -fsS http://localhost:${MYTREND_PORT}/api/health" && echo " ← health OK" || true ;;
  logs)    check_prereqs; remote_compose "logs -f --tail=100" ;;
  *) echo "사용법: ./deploy.sh [up|down|restart|status|logs]"; exit 1 ;;
esac
