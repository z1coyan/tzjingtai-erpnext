#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Load .env if present
# shellcheck disable=SC1091
[ -f "${REPO_ROOT}/.env" ] && source "${REPO_ROOT}/.env"

CUSTOM_IMAGE="${CUSTOM_IMAGE:-synie-erpnext}"
FRAPPE_BRANCH="${FRAPPE_BRANCH:-version-16}"
GIT_HASH="$(git -C "${REPO_ROOT}" rev-parse --short HEAD 2>/dev/null || echo 'dev')"
CUSTOM_TAG="${CUSTOM_TAG:-${GIT_HASH}}"

echo "==> Building image: ${CUSTOM_IMAGE}:${CUSTOM_TAG}"
echo "    Frappe branch:  ${FRAPPE_BRANCH}"

docker build \
  --build-arg="FRAPPE_BRANCH=${FRAPPE_BRANCH}" \
  --tag="${CUSTOM_IMAGE}:${CUSTOM_TAG}" \
  --tag="${CUSTOM_IMAGE}:latest" \
  --file="${REPO_ROOT}/build/Containerfile" \
  "${REPO_ROOT}"

echo "==> Done: ${CUSTOM_IMAGE}:${CUSTOM_TAG}"
