#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Load .env if present
# shellcheck disable=SC1091
[ -f "${REPO_ROOT}/.env" ] && source "${REPO_ROOT}/.env"

CUSTOM_IMAGE="${CUSTOM_IMAGE:-tzjingtai-erpnext}"
CUSTOM_TAG="${CUSTOM_TAG:-latest}"
DEPLOY_HOST="${DEPLOY_HOST:?ERROR: 请在 .env 中设置 DEPLOY_HOST（如 root@your-server）}"

echo "==> Pushing ${CUSTOM_IMAGE}:${CUSTOM_TAG} to ${DEPLOY_HOST}"
docker save "${CUSTOM_IMAGE}:${CUSTOM_TAG}" | gzip | ssh "${DEPLOY_HOST}" 'gunzip | docker load'

echo "==> Done"
