#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE_FILE="${REPO_ROOT}/docker-compose.yaml"
PROJECT_NAME="${PROJECT_NAME:-synie-erpnext}"

if [ ! -f "${COMPOSE_FILE}" ]; then
  echo "ERROR: docker-compose.yaml not found. Run 'make gen' first." >&2
  exit 1
fi

echo "==> Deploying project: ${PROJECT_NAME}"
docker compose -p "${PROJECT_NAME}" -f "${COMPOSE_FILE}" up -d --remove-orphans

echo "==> Services:"
docker compose -p "${PROJECT_NAME}" -f "${COMPOSE_FILE}" ps
