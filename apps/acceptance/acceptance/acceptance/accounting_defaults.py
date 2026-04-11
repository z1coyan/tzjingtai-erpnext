# Copyright (c) 2026, 台州京泰 and contributors
# For license information, please see license.txt
"""承兑汇票模块的默认会计科目常量.

单公司部署, 科目名称硬编码. Controller 在 validate() 阶段据此自动回填
Bill Discount / Bill Payment / Bill Receive / Bill Transfer 上的科目字段.

**核心设计**: 贴现 / 兑付 的"银行侧"不允许直接打真实银行叶子账户, 必须落到
`11215 票据清算中`. 每周导入银行流水时由对账人把相应的到账流水对方科目也写到
`11215 票据清算中`, 于是清算中账户借贷自然相抵, 残余 = 未对账项. 这样避免
acceptance 单据和银行流水 JE 对同一笔现金运动重复记账.
"""

# 票据清算中 (suspense account) — 贴现/兑付 与银行流水对账的中转科目.
# 任何与银行流水有关的 acceptance 会计动作都先落到这里, 等银行流水导入时冲减.
CLEARING_ACCOUNT = "11215 - 票据清算中 - 台州京泰"

# 应收票据 leaf (商承 + 银承均走此科目; 若未来采用 CAS 22 新准则区分银承走
# "应收款项融资", 需按 bill_type 分流再改这里).
NOTES_RECEIVABLE_ACCOUNT = "11211 - 应收票据 - 台州京泰"

# 财务费用-票据贴现利息, 承兑贴现利息计入.
DISCOUNT_INTEREST_ACCOUNT = "财务费用_票据贴现利息 - 台州京泰"

# 公司 name.
DEFAULT_COMPANY = "台州京泰电气有限公司"
