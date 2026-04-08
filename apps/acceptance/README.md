# Acceptance — 承兑汇票管理模块

基于新一代票据系统（票据包号 + 子票区间）的电子商业承兑汇票全生命周期管理 Frappe Custom App，挂载在 ERPNext 会计模块下运行。

## 功能概览

### 核心业务

| 业务 | DocType | 说明 |
|------|---------|------|
| 票据台账 | Bill of Exchange | 核心主表，记录票据完整信息与状态，支持子票拆分 |
| 票据接收 | Bill Receive | 企业收到客户/供应商以承兑汇票支付时登记签收，支持 OCR 识别票面 |
| 票据转让 | Bill Transfer | 将持有票据背书转让给供应商/客户，支持部分金额转让（子票拆分） |
| 提前贴现 | Bill Discount | 未到期票据向银行贴现，自动计算贴现利息和实际到账金额 |
| 到期兑付 | Bill Payment | 票据到期后确认银行资金到账，完成票据生命周期 |

### 辅助功能

- **阿里云 OCR 识别** — 拍照/上传票据图片，自动识别票面信息并回填表单字段
- **自动会计凭证** — 票据接收/转让提交时自动生成 Journal Entry（含 Payment Ledger Entry，支持发票核销）；贴现/兑付生成 GL Entry
- **背书链追踪** — 完整记录票据在各持票人之间的流转历史，支持背书记录报表查询
- **到期提醒** — 每日定时任务扫描即将到期票据，发送系统通知
- **发票集成** — 在销售发票上可直接创建票据接收，在采购发票上可直接创建票据转让

### Workspace 看板

- 侧边菜单快速导航各 DocType
- 统计卡片：未到期票据总数、7天内到期、30天内到期
- 到期分布图表

## DocType 清单

| DocType | 类型 | 说明 |
|---------|------|------|
| Bill of Exchange | 主表，可提交 | 票据台账，核心票据信息与状态机 |
| Bill Sub Ticket | 子表 | 子票区间记录 |
| Endorsement Chain | 子表 | 票据台账的背书链条历史（含 source_doctype/source_docname 追溯来源单据） |
| Bill Receive | 主表，可提交 | 票据接收（含 OCR） |
| Bill Transfer | 主表，可提交 | 票据转让（含子票拆分） |
| Bill Discount | 主表，可提交 | 提前贴现 |
| Bill Payment | 主表，可提交 | 到期兑付 |
| OCR Settings | Single | 阿里云 OCR 凭证配置 |

## 数据流

```
Sales Invoice ──→ Bill Receive ──→ Bill of Exchange (status: Received - Circulating)
                                        │
                   ┌────────────┬────────┴────────┬──────────┐
                   ↓            ↓                 ↓          ↓
            Bill Transfer  Bill Discount    Bill Payment   Sub Ticket Split
            (Endorsed)     (Discounted)     (Settled)
                   ↓            ↓                 ↓
           Purchase Invoice  Bank Entry      Bank Entry
```

## 票据编号规则

- **票据包号**: 30 位数字，首位标识票据种类（5=银票 6=商票 7=供应链商票 8=供应链银票）
- **子票区间**: 每个序号对应 0.01 元，金额 = (结束号 - 起始号 + 1) × 0.01
- **拆分规则**: 票据包号不变，按金额计算拆分点生成新子票区间，拆分层级上限 500 人

## 会计分录

| 操作 | 借方 | 贷方 | 凭证方式 |
|------|------|------|----------|
| 票据接收（客户） | 应收票据 | 应收账款 | Journal Entry → 自动生成 PLE，核销 Sales Invoice |
| 票据接收（供应商找回） | 应收票据 | 应付账款 | Journal Entry → 自动生成 PLE，核销 Purchase Invoice |
| 票据转让（供应商） | 应付账款 | 应收票据 | Journal Entry → 自动生成 PLE，核销 Purchase Invoice |
| 票据转让（客户找钱） | 应收账款 | 应收票据 | Journal Entry → 自动生成 PLE，核销 Sales Invoice |
| 提前贴现 | 银行存款 + 财务费用-贴现利息 | 应收票据 | GL Entry |
| 到期兑付 | 银行存款 | 应收票据 | GL Entry |

> 票据接收和转让支持 `party_type`（Customer / Supplier）动态选择对手方，覆盖常规业务和找钱/找回等少见场景。

## 技术依赖

- Frappe Framework v16+
- ERPNext v16+
- `alibabacloud_ocr_api20210707` — 阿里云 OCR SDK（票据识别）

## 目录结构

```
acceptance/
├── hooks.py                              # doctype_js、scheduler_events、fixtures
├── locale/zh.po                          # 中文翻译（所有标识符为英文，翻译在此）
├── public/js/
│   ├── sales_invoice.js                  # 销售发票 → 创建票据接收
│   └── purchase_invoice.js               # 采购发票 → 创建票据转让
└── acceptance/
    ├── ocr_service.py                    # 阿里云 OCR 集成（@frappe.whitelist）
    ├── dashboard_stats.py                # Workspace 统计数据接口
    ├── dashboard_chart_source/           # 到期分布图表数据源
    ├── number_card/                      # 统计卡片定义
    ├── report/
    │   └── endorsement_record/           # 背书记录报表（Script Report）
    ├── workspace/acceptance_bill/        # Workspace 导航配置
    └── doctype/
        ├── bill_of_exchange/             # 票据台账
        ├── bill_sub_ticket/              # 子票记录
        ├── endorsement_chain/            # 背书链条
        ├── bill_receive/                 # 票据接收
        ├── bill_transfer/                # 票据转让
        ├── bill_discount/                # 提前贴现
        ├── bill_payment/                 # 到期兑付
        └── ocr_settings/                 # OCR 配置
```

## 命名规范

- 所有标识符（DocType 名称、fieldname、Select 选项值、状态枚举）使用英文
- 中文仅出现在 `locale/zh.po` 翻译文件中
- Python 代码用 `_("English text")`，JS 代码用 `__("English text")` 包裹可见字符串
