# acceptance — 承兑汇票管理 Frappe Custom App

## 项目定位
基于新一代票据系统（票据包号+子票区间）的电子商业承兑汇票全生命周期管理，挂在 ERPNext 会计模块下。

## 技术栈
- Frappe v16 Custom App，依赖 frappe + erpnext
- 阿里云 OCR SDK (`alibabacloud_ocr_api20210707`) 用于票据图片识别
- 票据接收/转让通过 `frappe.new_doc("Journal Entry")` 生成日记账（自动创建 GL + PLE，支持发票核销）
- 贴现/兑付通过 `erpnext.accounts.general_ledger.make_gl_entries` 生成 GL Entry
- 对手方科目通过 `erpnext.accounts.party.get_party_account` 自动获取

## 目录结构
```
acceptance/
├── hooks.py                          # doctype_js(SI/PI按钮)、scheduler(到期提醒)
├── acceptance/workspace/acceptance_bill/acceptance_bill.json  # Workspace导航（Desk首页入口）
├── public/js/
│   ├── sales_invoice.js              # 销售发票→创建票据接收
│   └── purchase_invoice.js           # 采购发票→创建票据转让
└── acceptance/
    ├── ocr_service.py                # 阿里云OCR集成（whitelist API）
    ├── report/
    │   └── endorsement_record/       # 背书记录报表（Script Report）
    └── doctype/
        ├── bill_of_exchange/         # 票据台账（核心主表，可提交）
        ├── bill_sub_ticket/          # 子票记录（子表）
        ├── endorsement_chain/        # 背书链条（子表，含 source_doctype/source_docname 追溯来源）
        ├── bill_receive/             # 票据接收（主表，可提交，含OCR）
        ├── bill_transfer/            # 票据转让（主表，可提交，含拆分）
        ├── bill_discount/            # 提前贴现（主表，可提交）
        ├── bill_payment/             # 到期兑付（主表，可提交）
        └── ocr_settings/             # OCR配置（Single单例）
```

## DocType 关系与数据流
```
Sales Invoice ──→ Bill Receive ──→ Bill of Exchange(status=Received - Circulating)
                       │                    │
                       │              endorsement_chain 子表（背书链条）
                       │                    │
                   ┌────────────┬────────┴────────┬──────────┐
                   ↓            ↓                 ↓          ↓
            Bill Transfer  Bill Discount    Bill Payment   Sub Ticket Split
            (Endorsed)     (Discounted)     (Settled)
                   ↓            ↓                 ↓
           Purchase Invoice  Bank Entry      Bank Entry

背书链条维护在 Bill of Exchange.endorsement_chain 子表中，由 Bill Receive / Bill Transfer
的 on_submit 直接写入，on_cancel 直接删除。不再使用独立的 Endorsement Log DocType。
Endorsement Record 报表从 endorsement_chain 子表联查 Bill of Exchange 生成。
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
Issued → Received - Circulating → Endorsement Pending → Endorsed
                                → Discount Pending → Discounted
                                → Payment Pending → Settled
                                → Split
```

### 会计分录
| 操作 | 借方 | 贷方 | 凭证方式 |
|------|------|------|----------|
| 票据接收（客户） | 应收票据 | 应收账款 | Journal Entry（自动 PLE，核销 SI） |
| 票据接收（供应商找回） | 应收票据 | 应付账款 | Journal Entry（自动 PLE，核销 PI） |
| 票据转让（供应商） | 应付账款 | 应收票据 | Journal Entry（自动 PLE，核销 PI） |
| 票据转让（客户找钱） | 应收账款 | 应收票据 | Journal Entry（自动 PLE，核销 SI） |
| 提前贴现 | 银行存款 + 财务费用-贴现利息 | 应收票据 | GL Entry |
| 到期兑付 | 银行存款 | 应收票据 | GL Entry |

> Bill Receive/Transfer 使用 `party_type`(Customer/Supplier) + `party`(Dynamic Link) 动态选择对手方。

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

## 命名规范

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

## 定时任务
`check_bill_maturity()` — 每日扫描到期前7天的票据，发送系统通知
