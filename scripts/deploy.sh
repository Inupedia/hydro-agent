#!/usr/bin/env bash
# Deploy Hydro-Agent as a Docker workbench.
#
#   ./scripts/deploy.sh              # this machine: local compose on a laptop, prod compose on the GPU host
#   ./scripts/deploy.sh local        # laptop: http://127.0.0.1:8000 with bind-mounted src
#   ./scripts/deploy.sh server       # from laptop: rsync to tencent_gpu and bring up https://hhu.ai.swhisxy.cn
#   ./scripts/deploy.sh up|logs|status|down
#
# Override SSH target / remote dir / public URL with env:
#   HYDRO_SSH_HOST=tencent_gpu HYDRO_REMOTE_DIR=~/hydro-agent HYDRO_PUBLIC_URL=https://hhu.ai.swhisxy.cn

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SSH_HOST="${HYDRO_SSH_HOST:-tencent_gpu}"
REMOTE_DIR="${HYDRO_REMOTE_DIR:-~/hydro-agent}"
PUBLIC_URL="${HYDRO_PUBLIC_URL:-https://hhu.ai.swhisxy.cn}"
HEALTH_PATH="/api/health"
WAIT_SECONDS="${HYDRO_HEALTH_WAIT:-300}"

on_gpu_host() {
  [[ -f /opt/traefik/traefik.yml ]] || [[ "$(hostname -s 2>/dev/null || true)" == "VM-0-11-ubuntu" ]]
}

compose_files_for_this_host() {
  if on_gpu_host; then
    echo "-f ${ROOT}/docker-compose.prod.yml"
  else
    echo "-f ${ROOT}/docker-compose.yml"
  fi
}

compose() {
  # shellcheck disable=SC2086
  docker compose ${COMPOSE_FILES:-$(compose_files_for_this_host)} "$@"
}

require_env() {
  if [[ ! -f "${ROOT}/.env" ]]; then
    cp "${ROOT}/.env.example" "${ROOT}/.env"
    echo "created ${ROOT}/.env from .env.example — fill SILICONFLOW_API_KEY and rerun." >&2
    exit 1
  fi
  if ! grep -q '^SILICONFLOW_API_KEY=.\+' "${ROOT}/.env"; then
    echo "${ROOT}/.env is missing SILICONFLOW_API_KEY." >&2
    exit 1
  fi
}

wait_http() {
  local url="$1"
  local deadline=$((SECONDS + WAIT_SECONDS))
  local body=""
  local curl_opts=(-fsS --max-time 8)
  [[ "${url}" == https://* ]] && curl_opts+=(-k)
  while (( SECONDS < deadline )); do
    if body="$(curl "${curl_opts[@]}" "${url}" 2>/dev/null)" && grep -q '"status":"ok"' <<<"${body}"; then
      echo "${body}"
      return 0
    fi
    sleep 3
  done
  echo "timed out waiting for ${url}" >&2
  curl -sS --max-time 8 "${url}" >&2 || true
  return 1
}

cmd_up() {
  require_env
  cd "${ROOT}"
  COMPOSE_FILES="${COMPOSE_FILES:-$(compose_files_for_this_host)}"
  echo "compose ${COMPOSE_FILES}"
  compose up --build -d
  if [[ "${COMPOSE_FILES}" == *docker-compose.prod.yml* ]]; then
    echo "waiting on loopback then ${PUBLIC_URL}"
    wait_http "http://127.0.0.1:8000${HEALTH_PATH}" >/dev/null
    wait_http "${PUBLIC_URL}${HEALTH_PATH}"
    echo "workbench: ${PUBLIC_URL}"
  else
    echo "waiting on http://127.0.0.1:8000"
    wait_http "http://127.0.0.1:8000${HEALTH_PATH}"
    echo "workbench: http://127.0.0.1:8000"
  fi
}

cmd_logs() {
  COMPOSE_FILES="$(compose_files_for_this_host)"
  compose logs -f --tail=200 workbench
}

cmd_status() {
  COMPOSE_FILES="$(compose_files_for_this_host)"
  compose ps
  echo
  if on_gpu_host; then
    curl -sS --max-time 8 "${PUBLIC_URL}${HEALTH_PATH}" || true
    echo
  else
    curl -sS --max-time 8 "http://127.0.0.1:8000${HEALTH_PATH}" || true
    echo
  fi
}

cmd_down() {
  COMPOSE_FILES="$(compose_files_for_this_host)"
  compose down
}

cmd_local() {
  COMPOSE_FILES="-f ${ROOT}/docker-compose.yml"
  cmd_up
}

rsync_to_server() {
  ssh -o BatchMode=yes "${SSH_HOST}" "mkdir -p ${REMOTE_DIR}"
  rsync -az --delete \
    --exclude '.git/' \
    --exclude '.venv/' \
    --exclude 'web/node_modules/' \
    --exclude 'web/dist/' \
    --exclude 'web/playwright-report/' \
    --exclude 'web/test-results/' \
    --exclude 'artifacts/' \
    --exclude 'scratch/' \
    --exclude '.pytest_cache/' \
    --exclude '.ruff_cache/' \
    --exclude '__pycache__/' \
    --exclude '.cursor/' \
    --exclude 'deploy.log' \
    --exclude '.DS_Store' \
    -e 'ssh -o BatchMode=yes' \
    "${ROOT}/" "${SSH_HOST}:${REMOTE_DIR}/"
}

cmd_server() {
  require_env
  echo "sync ${ROOT} -> ${SSH_HOST}:${REMOTE_DIR}"
  rsync_to_server
  ssh -o BatchMode=yes "${SSH_HOST}" "cd ${REMOTE_DIR} && ./scripts/deploy.sh up"
}

usage() {
  cat <<EOF
Usage: $(basename "$0") [command]

  (default)  up on this machine (prod compose if this is the GPU host)
  local      laptop workbench at http://127.0.0.1:8000
  server     rsync to ${SSH_HOST} and publish ${PUBLIC_URL}
  up         build and start
  logs       follow workbench logs
  status     compose ps + health
  down       stop containers
EOF
}

main() {
  local cmd="${1:-up}"
  case "${cmd}" in
    up) cmd_up ;;
    local) cmd_local ;;
    server) cmd_server ;;
    logs) cmd_logs ;;
    status) cmd_status ;;
    down) cmd_down ;;
    -h|--help|help) usage ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
}

main "$@"
