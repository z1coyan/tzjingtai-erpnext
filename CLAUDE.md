# 台州京泰ERPNext部署项目规范

必须使用中文作为思考、输出、代码注释语言

## 容器化部署铁律

- **禁止在 docker build / deploy 之后要求进入容器执行任何可能导致生产css、js破坏 bench 命令**。生产环境中在容器内跑 bench 极有可能打挂 CSS/JS 静态资源导致线上故障。
- Containerfile 中 `bench build` 生成的静态资源是唯一可信来源，deploy 时只做文件复制，不做任何编译或数据库操作。

### app 安装完全由 configurator 自动完成

**禁止任何人工介入**。追加 app 的完整流程只有两步：

1. 把 app 加进 `build/apps.json`（远程 app）或 `apps/` 目录（本地 app），`git commit && git push`。
2. 在 Dokploy 控制台点 **Deploy**。完。

Dokploy deploy 会触发：

- 重新 build 镜像（app 源码 + 预编译 CSS/JS 被 baked-in）
- 起 `configurator` 一次性容器，由 `build/resources/configurator-init.sh` 执行：
  1. 把镜像里的 `sites-assets` 同步到 sites volume（保证资源永远和镜像一致）
  2. 写入 common_site_config（db、redis、socketio 配置）
  3. **flushall redis-cache** —— 清掉上一轮镜像的 `assets_json` / `bootinfo` / 页面缓存，避免浏览器拉 404 的老 bundle hash
  4. 遍历所有已存在的 site，比对 `sites/apps.txt` 与 `site_config.json.installed_apps`，对缺失的 app 自动 `bench --site <site> install-app <app> --skip-assets`
- configurator 跑完后 backend / frontend / workers 才启动，拿到的就是已经配置好、app 已安装、缓存已清空的干净状态

`configurator-init.sh` 是这条通道的**唯一实现**。在任何时候、任何情况下：

- 禁止手工 `docker compose exec backend bench ...`（包括 install-app）
- 禁止 `bench migrate` / `bench build` / `bench clear-cache` / `bench get-app` / `bench update`
- 禁止写 `scripts/install-app.sh` 之类的外挂脚本绕过 configurator
- 添加新 app 只改 `apps.json` + git push + Dokploy Deploy，绝无其他姿势

`redis-cache` 容器在 compose 里显式关闭了 RDB/AOF 持久化（`--save "" --appendonly no`），配合 configurator 的 flushall，双重保证任何 deploy 都从干净的缓存状态起步。

## 项目自建APP命名规范

### 铁律：所有标识符必须使用英文

DocType 名称、fieldname、Section/Column Break label、Select 选项值、状态枚举值、Python 方法名、JS 事件名 —— 一律使用英文。
中文仅出现在翻译文件 `acceptance/locale/zh.po` 中，作为 UI 显示文本。

### DocType 名称

- 使用 Title Case 英文短语，如 `Bill of Exchange`、`Endorsement Chain`
- 禁止使用中文作为 DocType name（数据库表名由此派生）

### 字段命名（fieldname）

- 使用 snake_case 英文，如 `bill_no`、`issue_date`、`drawer_name`
- label 使用英文 Title Case，如 `Bill No`、`Issue Date`、`Drawer Name`
- 禁止使用拼音或中文作为 fieldname 或 label

### Select 选项值

- 使用英文短语，如 `Received - Circulating`、`Bank Acceptance Bill`
- 禁止在 options 中直接写中文

### Section Break / Column Break

- label 使用英文，如 `Bill Details`、`Accounting`

### 翻译要求

- 每新增一个 DocType、字段 label、Select 选项值或用户可见消息，必须同步在 `acceptance/locale/zh.po` 中添加对应的中文翻译条目
- 翻译文件格式遵循 GNU gettext PO 标准：
  ```
  #. 注释说明字段来源
  msgid "English Text"
  msgstr "中文翻译"
  ```
- Python 代码中用户可见字符串必须用 `_("English text")` 包裹
- JS 代码中用户可见字符串必须用 `__("English text")` 包裹
- 验证消息、提示语等运行时文本同样需要翻译条目
