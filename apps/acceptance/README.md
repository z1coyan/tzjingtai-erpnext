# Acceptance — Bill of Exchange Management

承兑汇票管理 ERPNext V16 / Frappe V16 自研 APP。

## 功能

- 承兑接收 / 背书转让 / 贴现 / 兑付 四类业务单据
- 主票号 + 多段子票区间独立流转
- 自动生成 Journal Entry，贴现 / 兑付 JE 可被 ERPNext 原生 Bank Reconciliation 直接匹配
- 阿里云 OCR 识别承兑汇票正面，一键回填
- 兼容无子票区间的老电票和纸票
- 数据面板 + Bill Register / Bill Ledger / Upcoming Maturity 报表

## 安装

放到 `apps/` 目录下 git push，Dokploy deploy 时 configurator 自动安装。
