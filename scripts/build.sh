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

# Collect optional mirror build args
MIRROR_ARGS=()
[ -n "${GITHUB_PROXY:-}" ]        && MIRROR_ARGS+=(--build-arg "GITHUB_PROXY=${GITHUB_PROXY}")
[ -n "${APT_MIRROR:-}" ]          && MIRROR_ARGS+=(--build-arg "APT_MIRROR=${APT_MIRROR}")
[ -n "${PIP_INDEX_URL:-}" ]       && MIRROR_ARGS+=(--build-arg "PIP_INDEX_URL=${PIP_INDEX_URL}")
[ -n "${PIP_TRUSTED_HOST:-}" ]    && MIRROR_ARGS+=(--build-arg "PIP_TRUSTED_HOST=${PIP_TRUSTED_HOST}")
[ -n "${NPM_REGISTRY:-}" ]        && MIRROR_ARGS+=(--build-arg "NPM_REGISTRY=${NPM_REGISTRY}")
[ -n "${NVM_SOURCE:-}" ]           && MIRROR_ARGS+=(--build-arg "NVM_INSTALL_SCRIPT=${NVM_SOURCE}")
[ -n "${NODE_MIRROR:-}" ]          && MIRROR_ARGS+=(--build-arg "NODE_MIRROR=${NODE_MIRROR}")
[ -n "${WKHTMLTOPDF_MIRROR:-}" ]   && MIRROR_ARGS+=(--build-arg "WKHTMLTOPDF_MIRROR=${WKHTMLTOPDF_MIRROR}")
[ -n "${REGISTRY_MIRROR:-}" ]      && MIRROR_ARGS+=(--build-arg "REGISTRY_MIRROR=${REGISTRY_MIRROR}")

if [ ${#MIRROR_ARGS[@]} -gt 0 ]; then
  echo "    Mirrors:        ${MIRROR_ARGS[*]}"
fi

docker build \
  --build-arg="FRAPPE_BRANCH=${FRAPPE_BRANCH}" \
  ${MIRROR_ARGS[@]+"${MIRROR_ARGS[@]}"} \
  --tag="${CUSTOM_IMAGE}:${CUSTOM_TAG}" \
  --tag="${CUSTOM_IMAGE}:latest" \
  --file="${REPO_ROOT}/build/Containerfile" \
  "${REPO_ROOT}"

echo "==> Done: ${CUSTOM_IMAGE}:${CUSTOM_TAG}"
