# 台州京泰ERPNext部署项目规范

必须使用中文作为思考、输出、代码注释语言

## 容器化部署铁律

- **禁止在 docker build / deploy 之后要求进入容器执行任何 bench 命令**（包括 bench migrate、bench build、bench clear-cache 等）。生产环境中在容器内跑 bench 极有可能打挂 CSS/JS 静态资源导致线上故障。
- 所有数据库变更（DocType schema、Workspace、fixtures 等）必须在 `bench install-app` 首次安装时一次性完成。后续代码更新只允许通过重新 build 镜像 + deploy 生效，不得依赖运行时 migrate。
- Containerfile 中 `bench build` 生成的静态资源是唯一可信来源，deploy 时只做文件复制，不做任何编译或数据库操作。
