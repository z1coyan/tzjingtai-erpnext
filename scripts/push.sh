#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Load .env if present
# shellcheck disable=SC1091
[ -f "${REPO_ROOT}/.env" ] && source "${REPO_ROOT}/.env"

REMOTE_IMAGE="${REMOTE_IMAGE:-ghcr.io/z1coyan/synie-erpnext}"
GIT_HASH="$(git -C "${REPO_ROOT}" rev-parse --short HEAD 2>/dev/null || echo 'dev')"
CUSTOM_TAG="${CUSTOM_TAG:-${GIT_HASH}}"

echo "==> Pushing: ${REMOTE_IMAGE}:${CUSTOM_TAG}"
docker push "${REMOTE_IMAGE}:${CUSTOM_TAG}"

echo "==> Pushing: ${REMOTE_IMAGE}:latest"
docker push "${REMOTE_IMAGE}:latest"

echo "==> Done"
