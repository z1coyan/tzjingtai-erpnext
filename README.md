# synie-erpnext

ERPNext 自部署 Mono-Repo —— 统一管理自研插件、第三方插件、Docker 镜像构建与生产部署。

## 前置条件

- Docker (或 Podman) + Docker Compose v2
- Make
- Git

## 快速开始

```bash
cp .env.example .env   # 按需修改配置
make build             # 构建 Docker 镜像
make gen               # 生成 docker-compose.yaml
make deploy            # 启动服务
```

等待所有服务就绪后，创建站点：

```bash
make site SITE=localhost PASS=admin DB_PASSWORD=changeme
```

访问 `http://localhost:8080`（使用 dev overlay 时）。

## 目录结构

```
compose.yaml          Dokploy / 生产部署用 compose 文件（已提交到 Git）
docker-compose.yaml   make gen 生成的 compose 文件（.gitignore，手动部署用）
apps/                 自研 Frappe 插件（每个子目录是一个标准 Frappe app）
build/
  ├── Containerfile   Docker 构建文件
  ├── apps.json       远程 app 清单（erpnext、hrms、erpnext_china 等）
  └── resources/      Nginx 模板和入口脚本
deploy/
  ├── compose.base.yaml     基础服务（backend, frontend, websocket, worker, scheduler）
  ├── compose.mariadb.yaml  MariaDB overlay
  ├── compose.redis.yaml    Redis overlay
  ├── compose.https.yaml    HTTPS / Traefik overlay
  └── compose.dev.yaml      本地开发 overlay（端口映射）
scripts/              自动化脚本（build.sh, gen-compose.sh, deploy.sh）
```

## Makefile 命令

| 命令                                          | 说明                                                    |
| --------------------------------------------- | ------------------------------------------------------- |
| `make build`                                  | 构建 Docker 镜像，tag 取 git short hash                 |
| `make push`                                   | 推送镜像到远程仓库（ghcr.io）                           |
| `make release`                                | 构建 + 推送镜像 + git push（一键发布）                  |
| `make gen`                                    | 生成 docker-compose.yaml（默认 overlay: mariadb,redis） |
| `make gen OVERLAYS=mariadb,redis,https`       | 指定 overlay 组合                                       |
| `make deploy`                                 | 启动/更新服务                                           |
| `make dev`                                    | 开发模式（mariadb + redis + dev overlay）               |
| `make logs`                                   | 查看日志                                                |
| `make ps`                                     | 查看服务状态                                            |
| `make down`                                   | 停止服务                                                |
| `make clean`                                  | 停止服务并删除数据卷                                    |
| `make site SITE=... PASS=... DB_PASSWORD=...` | 创建新站点                                              |

## 上线流程

> **铁律**：镜像是唯一可信来源。所有代码和静态资源变更只通过重新构建镜像生效。运行中的容器内**绝不允许**执行 `bench build`、`bench migrate`、`bench clear-cache` 等命令，否则极有可能打挂 CSS/JS 静态资源导致线上故障。

### 部署架构

```
本地机: 改代码 → make release（构建镜像 + 推送 ghcr.io + git push）
                        ↓                           ↓
                   ghcr.io 镜像仓库           Dokploy 检测 git push
                        ↓                           ↓
                  Dokploy: docker compose pull → docker compose up -d
```

项目支持两种部署方式：

| 方式 | 使用的 compose 文件 | 镜像来源 | 适用场景 |
| ---- | ------------------- | -------- | -------- |
| **Dokploy（推荐）** | `compose.yaml`（已提交到 Git） | 从 ghcr.io 拉取 | 生产环境 |
| **手动部署** | `docker-compose.yaml`（由 `make gen` 生成） | 本地构建 | 本地开发 |

---

### Dokploy 部署（推荐）

#### 前置：本地机登录 ghcr.io

```bash
# 使用 GitHub Personal Access Token（需 write:packages 权限）
echo <YOUR_GITHUB_TOKEN> | docker login ghcr.io -u <YOUR_GITHUB_USERNAME> --password-stdin
```

#### 首次配置

1. **本地机** — 构建并推送镜像

   ```bash
   make build    # 构建镜像
   make push     # 推送到 ghcr.io
   git push origin main
   ```

2. **Dokploy 控制台** — 创建 Compose 项目
   - 数据源选择 **Git**，填入仓库地址
   - Compose 文件路径填 `compose.yaml`
   - 在环境变量中配置：

   ```
   DB_PASSWORD=<数据库密码>

   # 如果服务器在国内，使用 ghcr 镜像加速拉取（推送始终走真实 ghcr.io）
   CUSTOM_IMAGE=ghcr.m.daocloud.io/z1coyan/synie-erpnext
   ```

3. **Dokploy 控制台** — 如果 ghcr.io 仓库是 private，需在 Dokploy 中配置 Docker Registry 认证（ghcr.io / 镜像站 + GitHub Token）

4. **Dokploy 控制台** — 点击 **Deploy**

5. **Dokploy 终端**（或 SSH） — 创建站点（首次唯一需要手动执行的步骤）：

   ```bash
   docker compose -f compose.yaml exec backend \
     bench new-site erp.example.com \
       --mariadb-user-host-login-scope='%' \
       --db-root-password=<DB_PASSWORD> \
       --admin-password=<ADMIN_PASSWORD> \
       --install-app erpnext \
       --install-app hrms \
       --install-app erpnext_china \
       --install-app acceptance \
       --set-default
   ```

#### 日常更新上线

本地机一条命令完成所有事：

```bash
make release   # = make build + make push + git push
```

Dokploy 检测到 git push 后自动拉取最新镜像并重启服务。`configurator` 服务每次启动时自动同步静态资源。

| 场景 | 本地机 | Dokploy | 手动操作 |
| ---- | :----: | :-----: | :------: |
| 框架小版本更新 | 改 `build/apps.json` → `make release` | 自动拉取镜像 + 部署 | 无 |
| 自定义 app 代码更新 | 改 `apps/` 下代码 → `make release` | 自动拉取镜像 + 部署 | 无 |
| 新增 app | 加 app → `make release` | 自动拉取镜像 + 部署 | Dokploy 终端执行 `bench install-app`（仅一次） |

> **注意**：小版本更新如果涉及 DB schema 变更（DocType 字段变化），需要评估影响。因为不执行 `bench migrate`，schema 不会自动更新。如确有 schema 变更，需考虑重建站点或编写自定义迁移脚本。

---

### 手动部署（本地开发 / 无 Dokploy）

#### 1. 首次上线

**本地机：**

```bash
git push origin main
```

**生产服务器：**

```bash
# 1. 克隆仓库
git clone <repo-url> && cd synie-erpnext

# 2. 配置环境变量
cp .env.example .env
vim .env   # 设置数据库密码、镜像源等

# 3. 构建镜像（所有 app 代码 + 前端资源全部打包进镜像）
make build

# 4. 生成 docker-compose.yaml
make gen

# 5. 启动所有服务
make deploy

# 6. 创建站点（唯一一次允许在容器内执行 bench 命令的时机）
make site SITE=erp.example.com DB_PASSWORD=changeme PASS=admin
```

#### 2. 框架更新上线（ERPNext / Frappe 小版本升级）

**本地机：**

```bash
vim build/apps.json   # 修改 branch 为具体 tag
git add build/apps.json && git commit -m "chore: upgrade erpnext to v16.x.x"
git push origin main
```

**生产服务器：**

```bash
git pull origin main && make build && make deploy
```

#### 3. 自定义 App 代码更新上线

**本地机：**

```bash
# 修改代码并推送
git add apps/acceptance && git commit -m "fix: xxx" && git push origin main
```

**生产服务器：**

```bash
git pull origin main && make build && make deploy
```

#### 4. 新增 App 后更新上线

**本地机：** 添加 app 到 `build/apps.json`（远程）或 `apps/`（本地），提交并推送。

**生产服务器：**

```bash
git pull origin main && make build && make deploy

# 在站点上安装新 app（仅一次，用于创建数据库表结构）
docker compose -p synie-erpnext exec backend \
  bench --site erp.example.com install-app new-app
```

#### 流程对照表

| 场景 | 本地机 | 生产服务器 | 容器内命令 |
| ---- | :----: | :--------: | :--------: |
| 首次上线 | `git push` | `make build` → `make gen` → `make deploy` → `make site` | `make site`（含 install-app） |
| 框架小版本更新 | 改 `apps.json` → `git push` | `git pull` → `make build` → `make deploy` | **禁止** |
| 自定义 app 代码更新 | 改代码 → `git push` | `git pull` → `make build` → `make deploy` | **禁止** |
| 新增 app | 加 app → `git push` | `git pull` → `make build` → `make deploy` → `bench install-app` | `bench install-app`（仅一次） |

## 技术栈

- Frappe / ERPNext version-16
- MariaDB 11.8
- Redis 6.2
- Nginx（内置于 frontend 服务）
- Traefik v3.6（可选 HTTPS）
