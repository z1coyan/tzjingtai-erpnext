# 台州京泰ERPNext部署项目规范

必须使用中文作为思考、输出、代码注释语言

## 容器化部署铁律

- **禁止在 docker build / deploy 之后要求进入容器执行任何 bench 命令**（包括 bench migrate、bench build、bench clear-cache、bench get-app、bench update 等）。生产环境中在容器内跑 bench 极有可能打挂 CSS/JS 静态资源导致线上故障。
- 所有数据库变更（DocType schema、Workspace、fixtures 等）必须在 `bench install-app` 首次安装时一次性完成。后续代码更新只允许通过重新 build 镜像 + deploy 生效，不得依赖运行时 migrate。
- Containerfile 中 `bench build` 生成的静态资源是唯一可信来源，deploy 时只做文件复制，不做任何编译或数据库操作。

### 唯一放开的通道：给已有站点追加 app

以下**仅**为"给一个已经在跑的 site 追加一个新 app"这一场景放开，其他任何 bench 子命令仍然禁止。

必须严格按以下顺序执行，否则视为违反铁律：

1. 在 `build/apps.json` 里加上新 app（或把本地 app 放进 `apps/`），然后 `make build && make push && make deploy`。**新镜像里必须已 baked-in 该 app 的源码及其预编译前端资源**。严禁在运行中的容器里 `bench get-app`。
2. 确认新镜像已 deploy 完毕、backend/frontend 容器已重启到新镜像后，执行一次性命令：
   ```
   docker compose exec backend bench --site <site> install-app <app> --skip-assets
   ```
   必须带 `--skip-assets`，禁止任何形式的运行时 asset rebuild。
3. 立刻 `docker compose restart backend frontend`，让 nginx 重新挂载镜像内的可信静态资源。
4. 该通道**只允许 `install-app` 一个子命令**。`bench migrate`、`bench build`、`bench clear-cache`、`bench get-app`、`bench update` 等在任何情况下仍然禁止。

脚本实现见 `scripts/install-app.sh`，优先使用脚本而不是手敲命令。
