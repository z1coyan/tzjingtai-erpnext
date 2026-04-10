#!/usr/bin/env bash
# 给已有站点一次性追加一个 app。
#
# 这是 CLAUDE.md / AGENTS.md "容器化部署铁律"里唯一放开的运行时 bench 通道，
# 只允许跑 `bench install-app --skip-assets`，不允许任何其他 bench 子命令。
#
# 前置条件（由调用者保证）：
#   1. build/apps.json 已包含目标 app，或 apps/ 目录下已放好本地 app
#   2. 已经 make build && make push && make deploy，新镜像 baked-in 该 app
#   3. backend / frontend 容器已经切到新镜像
#
# 用法：
#   scripts/install-app.sh <site> <app>
# 例：
#   scripts/install-app.sh erp.jingtai.local offsite_backups

set -euo pipefail

if [ $# -ne 2 ]; then
  echo "用法: $0 <site> <app>" >&2
  echo "例:   $0 erp.jingtai.local offsite_backups" >&2
  exit 1
fi

SITE="$1"
APP="$2"

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE_FILE="${REPO_ROOT}/docker-compose.yaml"
PROJECT_NAME="${PROJECT_NAME:-synie-erpnext}"

if [ ! -f "${COMPOSE_FILE}" ]; then
  echo "ERROR: docker-compose.yaml 不存在，请先 make gen && make deploy" >&2
  exit 1
fi

compose() {
  docker compose -p "${PROJECT_NAME}" -f "${COMPOSE_FILE}" "$@"
}

echo "==> 校验 backend 容器运行中"
if ! compose ps --status running backend | grep -q backend; then
  echo "ERROR: backend 容器未运行，先 make deploy" >&2
  exit 1
fi

echo "==> 校验镜像内已 baked-in app: ${APP}"
# app 源码必须在镜像里（build 期通过 apps.json 或 apps/ 放进去），
# 否则会退化成运行时 get-app，触发 yarn/npm 拉依赖，打挂前端资源。
if ! compose exec -T backend test -d "apps/${APP}"; then
  echo "ERROR: apps/${APP} 不在镜像里。" >&2
  echo "       先把 ${APP} 加进 build/apps.json 或 apps/，然后 make build && make push && make deploy。" >&2
  echo "       严禁在运行中的容器里 bench get-app。" >&2
  exit 1
fi

echo "==> 校验 site 存在: ${SITE}"
if ! compose exec -T backend test -d "sites/${SITE}"; then
  echo "ERROR: sites/${SITE} 不存在" >&2
  exit 1
fi

echo "==> 校验 app 是否已安装"
if compose exec -T backend bench --site "${SITE}" list-apps 2>/dev/null | grep -qw "${APP}"; then
  echo "    ${APP} 已在 ${SITE} 的 installed_apps 列表里，跳过"
  exit 0
fi

echo "==> 执行 install-app（--skip-assets，禁止运行时 asset rebuild）"
compose exec -T backend bench --site "${SITE}" install-app "${APP}" --skip-assets

echo "==> 重启 backend / frontend，让 nginx 重新挂载镜像内可信静态资源"
compose restart backend frontend

echo "==> 校验安装结果"
compose exec -T backend bench --site "${SITE}" list-apps

echo "==> 完成。浏览器强刷验证 Desk UI 及 ${APP} 相关页面。"
