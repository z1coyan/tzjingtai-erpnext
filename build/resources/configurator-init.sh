#!/usr/bin/env bash
# 一次性 bootstrap 脚本，由 docker-compose 里的 `configurator` 服务在每次 deploy 时调用。
#
# 它承担以下几件事，全部都是 "新镜像 deploy 时" 的幂等操作：
#   1. 写入 common_site_config.json 里的 db / redis / socketio 配置（原 configurator 职责）
#   2. 把镜像内 baked-in 的 sites-assets 同步到共享 sites volume（保证 CSS/JS 永远是镜像版本）
#   3. 清空 redis-cache —— 避免老的 assets_json / bootinfo / 页面缓存引用已经被新 hash 替换的旧 bundle
#   4. 对每个已存在的 site，比对 sites/apps.txt 与 site_config.json.installed_apps，
#      自动安装新加入的 app（install-app 只动 DB，不会重建 sites/assets）
#   5. 对每个已存在的 site 跑 bench sync-fixtures —— install-app 只在"新装 app"时
#      同步 fixtures，对已装 app 的 fixtures 改动（Custom Field / Property Setter /
#      Workflow 等）无效。这一步补上这个盲区。sync-fixtures 只读镜像里的
#      fixtures/*.json 往 DB 写，不触碰 sites/assets，对 CSS/JS 静态资源安全。
#
# 这是 CLAUDE.md / AGENTS.md 容器化部署铁律里"唯一放开的通道"的**唯一实现**。
# 禁止在这个脚本之外、在运行中的容器里手工跑任何 bench 子命令。脚本内部也只允许
# 以下 bench 子命令：set-config / install-app / execute（仅 frappe.utils.fixtures.sync_fixtures）。

set -euo pipefail

cd /home/frappe/frappe-bench

echo "==> [configurator] 同步镜像内 apps.txt 和 sites/assets"
ls -1 apps > sites/apps.txt
rm -rf sites/assets
cp -r /home/frappe/frappe-bench/sites-assets sites/assets

echo "==> [configurator] 写入 common_site_config"
bench set-config -g  db_host          "${DB_HOST}"
bench set-config -gp db_port          "${DB_PORT}"
bench set-config -g  redis_cache      "redis://${REDIS_CACHE}"
bench set-config -g  redis_queue      "redis://${REDIS_QUEUE}"
bench set-config -g  redis_socketio   "redis://${REDIS_QUEUE}"
bench set-config -gp socketio_port    "${SOCKETIO_PORT}"
bench set-config -g  chromium_path    "/usr/bin/chromium-headless-shell"

# redis-cache 里可能存着上一轮镜像的 assets_json / bootinfo / 页面缓存，
# 这些缓存里嵌着老的 bundle hash。新镜像换了 hash 之后必须清掉，否则
# 浏览器会拉 404 的 CSS/JS 导致 UI 挂掉 —— 这是 2026-04-10 事故的根因。
REDIS_CACHE_HOST="${REDIS_CACHE%%:*}"
REDIS_CACHE_PORT="${REDIS_CACHE##*:}"
echo "==> [configurator] 清空 redis-cache (${REDIS_CACHE_HOST}:${REDIS_CACHE_PORT})"
redis-cli -h "${REDIS_CACHE_HOST}" -p "${REDIS_CACHE_PORT}" flushall

# 遍历所有已存在的 site，比对 sites/apps.txt (镜像里的 bench-level app 列表) 与
# site 自己的 installed_apps，把差集自动 install 上去。
#
# bench install-app 在 v16 没有 --skip-assets 选项，也不需要 —— install-app
# 只做 DB schema + fixtures，不触碰 sites/assets，所以镜像里 baked-in 的
# 静态资源不会被重建、不会覆盖磁盘上的 hash 文件。
#
# 首次 deploy 时 sites/ 下可能没有任何站点（user 还没跑 make site），
# 这段循环就是 no-op；不会阻塞 configurator。
BENCH_APPS=$(cat sites/apps.txt)

for site_config in sites/*/site_config.json; do
  [ -f "$site_config" ] || continue
  site_dir=$(dirname "$site_config")
  site=$(basename "$site_dir")

  # 跳过特殊目录
  case "$site" in
    assets|.*) continue ;;
  esac

  installed=$(python3 -c "
import json, sys
try:
    data = json.load(open('$site_config'))
    print(' '.join(data.get('installed_apps', [])))
except Exception as e:
    sys.stderr.write(f'read $site_config failed: {e}\n')
    sys.exit(0)
")

  for app in $BENCH_APPS; do
    # frappe 是隐式安装，不显式出现在 installed_apps 里也没关系
    [ "$app" = "frappe" ] && continue

    if ! echo " $installed " | grep -q " $app "; then
      echo "==> [configurator] ${site}: 安装 ${app}"
      bench --site "$site" install-app "$app"
    fi
  done

  # 把镜像里 fixtures/*.json 的变更刷进 DB（Custom Field / Property Setter /
  # Workflow 等）。install-app 已经自带 sync_fixtures，所以这一步对"刚装完
  # 的新 app"是幂等 no-op；对"已存在 app 里加了新 fixtures"是补齐漏洞。
  #
  # v16 的 bench CLI 没有独立的 sync-fixtures 子命令（只有 export-fixtures），
  # 所以直接通过 bench execute 调用底层函数。sync_fixtures() 只读 fixtures/*.json
  # 往 DB 写，不触碰 sites/assets。
  echo "==> [configurator] ${site}: 同步 fixtures"
  bench --site "$site" execute frappe.utils.fixtures.sync_fixtures
done

echo "==> [configurator] 完成"
