#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEPLOY_DIR="${REPO_ROOT}/deploy"
ENV_FILE="${REPO_ROOT}/.env"

# Default overlays: mariadb + redis
OVERLAYS="${1:-mariadb,redis}"

if [ ! -f "${ENV_FILE}" ]; then
  echo "WARNING: .env not found. Copy .env.example to .env first." >&2
fi

CMD="docker compose"
[ -f "${ENV_FILE}" ] && CMD+=" --env-file ${ENV_FILE}"
CMD+=" -f ${DEPLOY_DIR}/compose.base.yaml"

IFS=',' read -ra PARTS <<< "${OVERLAYS}"
for part in "${PARTS[@]}"; do
  part="$(echo "$part" | xargs)"  # trim whitespace
  overlay="${DEPLOY_DIR}/compose.${part}.yaml"
  if [ ! -f "${overlay}" ]; then
    echo "ERROR: Overlay not found: ${overlay}" >&2
    exit 1
  fi
  CMD+=" -f ${overlay}"
done

CMD+=" config"

echo "==> Generating docker-compose.yaml (overlays: ${OVERLAYS})"
eval "${CMD}" > "${REPO_ROOT}/docker-compose.yaml"
echo "==> Written: ${REPO_ROOT}/docker-compose.yaml"
