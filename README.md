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
| `make gen`                                    | 生成 docker-compose.yaml（默认 overlay: mariadb,redis） |
| `make gen OVERLAYS=mariadb,redis,https`       | 指定 overlay 组合                                       |
| `make deploy`                                 | 启动/更新服务                                           |
| `make dev`                                    | 开发模式（mariadb + redis + dev overlay）               |
| `make logs`                                   | 查看日志                                                |
| `make ps`                                     | 查看服务状态                                            |
| `make down`                                   | 停止服务                                                |
| `make clean`                                  | 停止服务并删除数据卷                                    |
| `make site SITE=... PASS=... DB_PASSWORD=...` | 创建新站点                                              |

## 新增插件

### 自研插件

1. 在 `apps/` 下创建标准 Frappe app 目录（含 `setup.py` 或 `pyproject.toml`）
2. `make build && make deploy`

### 第三方插件

1. 在 `build/apps.json` 中添加 `{"url": "...", "branch": "..."}` 记录
2. `make build && make deploy`

## 技术栈

- Frappe / ERPNext version-16
- MariaDB 11.8
- Redis 6.2
- Nginx（内置于 frontend 服务）
- Traefik v3.6（可选 HTTPS）
