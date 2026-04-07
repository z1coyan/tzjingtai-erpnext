# acceptance — 承兑汇票管理 Frappe Custom App

## 项目定位
基于新一代票据系统（票据包号+子票区间）的电子商业承兑汇票全生命周期管理，挂在 ERPNext 会计模块下。

## 技术栈
- Frappe v16 Custom App，依赖 frappe + erpnext
- 阿里云 OCR SDK (`alibabacloud_ocr_api20210707`) 用于票据图片识别
- 会计凭证通过 `erpnext.accounts.general_ledger.make_gl_entries` 生成

## 目录结构
```
acceptance/
├── hooks.py                          # doctype_js(SI/PI按钮)、scheduler(到期提醒)
├── config/desktop.py                 # 桌面模块入口
├── workspace/acceptance/acceptance.json  # Workspace导航，parent_page=Accounting
├── public/js/
│   ├── sales_invoice.js              # 销售发票→创建票据接收
│   └── purchase_invoice.js           # 采购发票→创建票据转让
└── acceptance/
    ├── ocr_service.py                # 阿里云OCR集成（whitelist API）
    └── doctype/
        ├── bill_of_exchange/         # 票据台账（核心主表，可提交）
        ├── bill_sub_ticket/          # 子票记录（子表）
        ├── endorsement_chain/        # 背书链条（子表）
        ├── endorsement_log/          # 背书记录（主表，可提交）
        ├── bill_receive/             # 票据接收（主表，可提交，含OCR）
        ├── bill_transfer/            # 票据转让（主表，可提交，含拆分）
        ├── bill_discount/            # 提前贴现（主表，可提交）
        ├── bill_payment/             # 到期兑付（主表，可提交）
        └── ocr_settings/             # OCR配置（Single单例）
```

## DocType 关系与数据流
```
Sales Invoice ──→ Bill Receive ──→ Bill of Exchange(状态=已收票-可流通)
                                        │
                   ┌────────────┬────────┴────────┬──────────┐
                   ↓            ↓                 ↓          ↓
            Bill Transfer  Bill Discount    Bill Payment   子票拆分
            (背书转让)      (提前贴现)       (到期兑付)    (Sub Ticket)
                   ↓            ↓                 ↓
           Purchase Invoice  Bank Entry      Bank Entry
```

## 关键业务规则

### 票据包号
30位数字，首位: 5=银票 6=商票 7=供应链商票 8=供应链银票。校验正则: `^[5678]\d{29}$`

### 子票区间与金额
- 每个序号 = 0.01元，金额 = (end - start + 1) × 0.01
- 区间为0表示不可拆分
- 拆分层级上限500人

### 状态机（controller代码控制，非Workflow）
```
已签发 → 已收票-可流通 → 背书待签收 → 已背书转让
                       → 贴现待确认 → 已贴现
                       → 提示付款中 → 已结清-已结束
                       → 已拆分
```

### 会计分录
| 操作 | 借方 | 贷方 |
|------|------|------|
| 票据接收 | 应收票据 | 应收账款 |
| 票据转让 | 应付账款 | 应收票据 |
| 提前贴现 | 银行存款 + 财务费用-贴现利息 | 应收票据 |
| 到期兑付 | 银行存款 | 应收票据 |

### 贴现利息计算
`利息 = 金额 × 年化利率/100 × 剩余天数 / 360`

## Controller 继承
- Bill Receive/Transfer/Discount/Payment 继承 `erpnext.controllers.accounts_controller.AccountsController`
- 必须包含 `posting_date`(或等效日期字段)、`company` 字段
- 所有可提交 DocType 包含 `amended_from` 字段

## OCR 集成
- 正面: `RecognizeBankAcceptance` — 结构化返回票据字段
- 背面: `RecognizeGeneralStructure` — 自定义Keys提取背书信息
- 凭证存储: OCR Settings (Single DocType)，AccessKey Secret 用 Password 字段加密
- 入口: `acceptance.acceptance.ocr_service.recognize_bill`（@frappe.whitelist）
- 子票区间不在OCR标准返回中，需用户手动输入

## 定时任务
`check_bill_maturity()` — 每日扫描到期前7天的票据，发送系统通知
