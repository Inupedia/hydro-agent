#!/usr/bin/env bash
# Deploy Hydro-Agent as a Docker workbench.
#
#   ./scripts/deploy.sh              # this machine: local compose on a laptop, prod compose on the GPU host
#   ./scripts/deploy.sh local        # rebuild frontend + backend and deploy locally
#   ./scripts/deploy.sh server       # sync, rebuild frontend + backend, deploy to server
#   ./scripts/deploy.sh local --fresh  # same, but disable Docker build cache
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
FRESH_BUILD=false

on_gpu_host() {
  [[ -f /opt/traefik/traefik.yml ]] || [[ "$(hostname -s 2>/dev/null || true)" == "VM-0-11-ubuntu" ]]
}

compose_files_for_this_host() {
  if on_gpu_host; then
    echo "${ROOT}/docker-compose.prod.yml"
  else
    echo "${ROOT}/docker-compose.yml"
  fi
}

compose() {
  local file="${COMPOSE_FILE:-$(compose_files_for_this_host)}"
  docker compose -f "${file}" "$@"
}

source_fingerprint() {
  python3 - "${ROOT}" <<'PY'
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
entries = (
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.prod.yml",
    "pyproject.toml",
    "uv.lock",
    "src",
    "skills",
    "workflow",
    "scripts",
    "web/index.html",
    "web/package.json",
    "web/package-lock.json",
    "web/vite.config.ts",
    "web/public",
    "web/src",
)
files: list[Path] = []
for entry in entries:
    path = root / entry
    if path.is_file():
        files.append(path)
    elif path.is_dir():
        files.extend(item for item in path.rglob("*") if item.is_file())

digest = hashlib.sha256()
for path in sorted(files, key=lambda item: item.relative_to(root).as_posix()):
    relative = path.relative_to(root).as_posix().encode("utf-8")
    digest.update(len(relative).to_bytes(4, "big"))
    digest.update(relative)
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
print(digest.hexdigest()[:20])
PY
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
  if [[ "${url}" == https://* && "${HYDRO_TLS_INSECURE:-0}" == "1" ]]; then
    curl_opts+=(-k)
  fi
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

verify_frontend() {
  local base_url="${1%/}"
  local curl_opts=(-fsS --max-time 15)
  local html=""
  local asset=""
  if [[ "${base_url}" == https://* && "${HYDRO_TLS_INSECURE:-0}" == "1" ]]; then
    curl_opts+=(-k)
  fi
  html="$(curl "${curl_opts[@]}" -H 'Cache-Control: no-cache' "${base_url}/")"
  asset="$(sed -nE 's|.*src="([^"]*/assets/[^"?]+\.js)[^"]*".*|\1|p' <<<"${html}" | head -n 1)"
  if [[ -z "${asset}" ]]; then
    echo "frontend verification failed: no hashed JavaScript asset in ${base_url}/" >&2
    return 1
  fi
  [[ "${asset}" == /* ]] || asset="/${asset}"
  curl "${curl_opts[@]}" -o /dev/null "${base_url}${asset}"
  echo "frontend_asset=${asset}"
}

verify_image_revision() {
  local expected="$1"
  local container_id=""
  local actual=""
  container_id="$(compose ps -q workbench)"
  if [[ -z "${container_id}" ]]; then
    echo "workbench container is not running" >&2
    return 1
  fi
  actual="$(docker inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "${container_id}")"
  if [[ "${actual}" != "${expected}" ]]; then
    echo "deployed image revision mismatch: expected=${expected} actual=${actual:-missing}" >&2
    return 1
  fi
  echo "image_revision=${actual}"
}

cmd_up() {
  require_env
  cd "${ROOT}"
  COMPOSE_FILE="${COMPOSE_FILE:-$(compose_files_for_this_host)}"
  local revision=""
  revision="$(source_fingerprint)"
  echo "compose_file=${COMPOSE_FILE}"
  echo "source_revision=${revision}"
  if [[ "${FRESH_BUILD}" == "true" ]]; then
    HYDRO_BUILD_REVISION="${revision}" compose build --no-cache workbench
  else
    HYDRO_BUILD_REVISION="${revision}" compose build workbench
  fi
  HYDRO_BUILD_REVISION="${revision}" compose up -d --force-recreate --remove-orphans workbench
  verify_image_revision "${revision}"
  if [[ "${COMPOSE_FILE}" == *docker-compose.prod.yml* ]]; then
    echo "waiting on loopback then ${PUBLIC_URL}"
    wait_http "http://127.0.0.1:8000${HEALTH_PATH}" >/dev/null
    wait_http "${PUBLIC_URL}${HEALTH_PATH}"
    verify_frontend "${PUBLIC_URL}"
    echo "workbench: ${PUBLIC_URL}"
  else
    echo "waiting on http://127.0.0.1:8000"
    wait_http "http://127.0.0.1:8000${HEALTH_PATH}"
    verify_frontend "http://127.0.0.1:8000"
    echo "workbench: http://127.0.0.1:8000"
  fi
}

cmd_logs() {
  COMPOSE_FILE="$(compose_files_for_this_host)"
  compose logs -f --tail=200 workbench
}

cmd_status() {
  COMPOSE_FILE="$(compose_files_for_this_host)"
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
  COMPOSE_FILE="$(compose_files_for_this_host)"
  compose down
}

cmd_local() {
  COMPOSE_FILE="${ROOT}/docker-compose.yml"
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
  local remote_args=""
  if [[ "${FRESH_BUILD}" == "true" ]]; then
    remote_args=" --fresh"
  fi
  ssh -o BatchMode=yes "${SSH_HOST}" "cd ${REMOTE_DIR} && ./scripts/deploy.sh up${remote_args}"
}

usage() {
  cat <<EOF
Usage: $(basename "$0") [command]

  (default)  up on this machine (prod compose if this is the GPU host)
  local      rebuild frontend + backend; deploy at http://127.0.0.1:8000
  server     sync and rebuild frontend + backend; publish ${PUBLIC_URL}
  up         rebuild frontend + backend on this machine
  logs       follow workbench logs
  status     compose ps + health
  down       stop containers

Options for local/server/up:
  --fresh   disable Docker build cache (slower; use for cache troubleshooting)
EOF
}

main() {
  local cmd="${1:-up}"
  shift || true
  while (( $# )); do
    case "$1" in
      --fresh) FRESH_BUILD=true ;;
      *)
        echo "unknown option: $1" >&2
        usage >&2
        exit 2
        ;;
    esac
    shift
  done
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
