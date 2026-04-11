# Copyright (c) 2026, 台州京泰 and contributors
# For license information, please see license.txt
"""期初数据导入辅助工具（仅管理员可调用）。

acceptance app 在首次安装时，Bill of Exchange.bill_no 带有 unique 约束。
该约束与 app 自身的拆分流程相互矛盾，且阻止期初历史数据（同一票号不同子票区间、
同一票号多次收入等）的导入。CLAUDE.md 禁止在生产环境中运行 bench migrate，
因此提供一个一次性的白名单方法，通过 ALTER TABLE 卸掉已建好的 unique 索引。

导入完成后该方法可以继续保留——重复调用是幂等的。
"""

import csv
import io
import re
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation

import frappe
from frappe import _
from frappe.utils import date_diff, getdate


@frappe.whitelist()
def drop_bill_no_unique_index():
	"""从 `tabBill of Exchange` 表上卸掉 bill_no 的 unique 索引。

	幂等：若索引不存在则直接返回。仅 Administrator / System Manager 可调用。
	"""
	if "System Manager" not in frappe.get_roles(frappe.session.user) and frappe.session.user != "Administrator":
		frappe.throw(_("Only System Manager or Administrator can run this"))

	table = "tabBill of Exchange"

	# 查找 bill_no 列上的所有非主键索引（MySQL information_schema）
	rows = frappe.db.sql(
		"""
		SELECT DISTINCT INDEX_NAME, NON_UNIQUE
		FROM information_schema.STATISTICS
		WHERE TABLE_SCHEMA = DATABASE()
		  AND TABLE_NAME = %s
		  AND COLUMN_NAME = 'bill_no'
		""",
		(table,),
		as_dict=True,
	)

	dropped = []
	for r in rows:
		idx = r["INDEX_NAME"]
		non_unique = r["NON_UNIQUE"]
		# 只卸 unique 索引（NON_UNIQUE=0），保留普通索引
		if non_unique == 0 and idx != "PRIMARY":
			frappe.db.sql(f"ALTER TABLE `{table}` DROP INDEX `{idx}`")
			dropped.append(idx)

	# 重新建一个普通（非唯一）索引加速按 bill_no 查询
	existing = frappe.db.sql(
		"""
		SELECT DISTINCT INDEX_NAME
		FROM information_schema.STATISTICS
		WHERE TABLE_SCHEMA = DATABASE()
		  AND TABLE_NAME = %s
		  AND COLUMN_NAME = 'bill_no'
		""",
		(table,),
		as_dict=True,
	)
	if not existing:
		frappe.db.sql(f"ALTER TABLE `{table}` ADD INDEX `bill_no` (`bill_no`)")

	frappe.db.commit()
	return {"dropped_unique_indexes": dropped}


@frappe.whitelist()
def purge_acceptance_data():
	"""清空所有 acceptance 业务单据以及它们产生的 GL/JE. 仅期初数据导入迭代使用.

	直接走 SQL, 绕过所有 on_cancel/link 检查. 会:
	- 删除 Bill Payment / Bill Transfer / Bill Discount / Bill Receive / Bill of Exchange
	- 删除 tabBill Sub Ticket, tabEndorsement Chain 子表
	- 删除 由 Bill Receive / Bill Transfer 产生的 Journal Entry (通过 user_remark 识别 "Bill Receive - " / "Bill Transfer - ")
	- 删除 voucher_type 为上述 doctype 的 GL Entry 与 Payment Ledger Entry
	- 删除 以那些 JE 为 voucher 的 GL Entry

	幂等: 再次运行不报错.
	"""
	if "System Manager" not in frappe.get_roles(frappe.session.user) and frappe.session.user != "Administrator":
		frappe.throw(_("Only System Manager or Administrator can run this"))

	counts = {}

	# 1. 找到待删的 JE (由 Bill Receive / Bill Transfer 产生)
	je_rows = frappe.db.sql(
		"""
		SELECT name FROM `tabJournal Entry`
		WHERE user_remark LIKE 'Bill Receive - %%' OR user_remark LIKE 'Bill Transfer - %%'
		"""
	)
	je_names = [r[0] for r in je_rows]

	# 2. 删 GL Entry - 既删 acceptance 自己生成的 (voucher_type 为 Bill Discount/Bill Payment),
	#    也删 JE 绑的 (voucher_type=Journal Entry 且 voucher_no 属于 je_names)
	counts["gl_from_discount_payment"] = frappe.db.sql(
		"""DELETE FROM `tabGL Entry` WHERE voucher_type IN ('Bill Discount', 'Bill Payment')"""
	)[0] if False else 0
	# rowcount 取法
	frappe.db.sql(
		"""DELETE FROM `tabGL Entry` WHERE voucher_type IN ('Bill Discount', 'Bill Payment')"""
	)
	counts["gl_from_discount_payment"] = "deleted"

	if je_names:
		placeholders = ",".join(["%s"] * len(je_names))
		frappe.db.sql(
			f"""DELETE FROM `tabGL Entry` WHERE voucher_type='Journal Entry' AND voucher_no IN ({placeholders})""",
			tuple(je_names),
		)
		frappe.db.sql(
			f"""DELETE FROM `tabPayment Ledger Entry` WHERE voucher_type='Journal Entry' AND voucher_no IN ({placeholders})""",
			tuple(je_names),
		)
	counts["gl_from_je"] = "deleted"

	# 3. 删 JE 本体 + 其子表
	if je_names:
		placeholders = ",".join(["%s"] * len(je_names))
		frappe.db.sql(
			f"""DELETE FROM `tabJournal Entry Account` WHERE parent IN ({placeholders})""",
			tuple(je_names),
		)
		frappe.db.sql(
			f"""DELETE FROM `tabJournal Entry` WHERE name IN ({placeholders})""",
			tuple(je_names),
		)
	counts["journal_entries"] = len(je_names)

	# 4. 删 acceptance 子表
	for child in ["tabBill Sub Ticket", "tabEndorsement Chain"]:
		frappe.db.sql(f"DELETE FROM `{child}`")
		counts[child] = "deleted"

	# 5. 删 acceptance 业务单据
	for t in [
		"tabBill Payment",
		"tabBill Transfer",
		"tabBill Discount",
		"tabBill Receive",
		"tabBill of Exchange",
	]:
		frappe.db.sql(f"DELETE FROM `{t}`")
		counts[t] = "deleted"

	frappe.db.commit()
	return counts


@frappe.whitelist()
def create_bank_subaccounts():
	"""创建 4 个银行叶子子账户 (作为 10020 的兄弟, 后续再把 10020 改 group).

	幂等: 已存在则跳过.
	"""
	if "System Manager" not in frappe.get_roles(frappe.session.user) and frappe.session.user != "Administrator":
		frappe.throw(_("Only System Manager or Administrator can run this"))

	parent = "10000 - 货币资金 - 台州京泰"
	company = "台州京泰电气有限公司"
	leaves = [
		("10021", "京泰工行"),
		("10022", "京泰宁波"),
		("10023", "东方农行"),
		("10024", "东方农商"),
	]
	created = []
	existing = []
	for num, name in leaves:
		full = f"{num} - {name} - 台州京泰"
		if frappe.db.exists("Account", full):
			existing.append(full)
			continue
		doc = frappe.get_doc({
			"doctype": "Account",
			"account_name": name,
			"account_number": num,
			"parent_account": parent,
			"company": company,
			"account_type": "Bank",
			"account_currency": "CNY",
			"is_group": 0,
		})
		doc.insert(ignore_permissions=True)
		created.append(doc.name)
	return {"created": created, "existing": existing}


@frappe.whitelist()
def rewrite_gl_account(gl_names_json, target_account):
	"""把指定 GL Entry 的 account 字段 SQL 改写为 target_account.

	gl_names_json: JSON 数组, GL Entry.name 列表
	target_account: 目标科目完整 name
	仅改 is_cancelled=0 的活跃条目.
	"""
	if "System Manager" not in frappe.get_roles(frappe.session.user) and frappe.session.user != "Administrator":
		frappe.throw(_("Only System Manager or Administrator can run this"))

	gl_names = frappe.parse_json(gl_names_json) if isinstance(gl_names_json, str) else gl_names_json
	if not gl_names:
		return {"updated": 0}

	# 校验目标账户存在且非 group
	target = frappe.db.get_value("Account", target_account, ["is_group", "name"], as_dict=True)
	if not target:
		frappe.throw(f"Target account {target_account} not found")
	if target.is_group:
		frappe.throw(f"Target account {target_account} is a group")

	placeholders = ",".join(["%s"] * len(gl_names))
	frappe.db.sql(
		f"UPDATE `tabGL Entry` SET account=%s WHERE name IN ({placeholders}) AND is_cancelled=0",
		(target_account, *gl_names),
	)
	frappe.db.commit()
	return {"updated": len(gl_names), "target": target_account}


@frappe.whitelist()
def convert_account_to_group(account_name):
	"""把一个叶子账户改成 group (SQL, 绕过 is_group 校验).

	前置条件: 该账户没有活跃 GL Entry (is_cancelled=0 数为 0).
	会同时清空 account_type (group 不能设 Bank/Receivable 等).
	"""
	if "System Manager" not in frappe.get_roles(frappe.session.user) and frappe.session.user != "Administrator":
		frappe.throw(_("Only System Manager or Administrator can run this"))

	cnt = frappe.db.sql(
		"SELECT COUNT(*) FROM `tabGL Entry` WHERE account=%s AND is_cancelled=0",
		(account_name,),
	)[0][0]
	if cnt > 0:
		frappe.throw(f"Account {account_name} still has {cnt} active GL entries, cannot convert to group")

	frappe.db.sql(
		"UPDATE `tabAccount` SET is_group=1, account_type='' WHERE name=%s",
		(account_name,),
	)
	frappe.db.commit()
	# 清 Account 文档缓存
	frappe.clear_document_cache("Account", account_name)
	return {"converted": account_name}


@frappe.whitelist()
def migrate_bill_bank_to_clearing(je_names_json, clearing_account, bank_accounts_json):
	"""把 Bill Discount/Payment 与 matched 银行流水 JE 的 "银行侧" 全部迁到票据清算中科目.

	背景: 历史数据双源(acceptance 与 bank flow xlsx) 对同一笔现金运动各记了一次,
	导致银行科目双重计账. 本函数通过 SQL 做标准的"票据清算"会计处理重构:

	1. 把 voucher_type in (Bill Discount, Bill Payment) 且 account 落在 bank_accounts
	   的 GL Entry, account 改成 clearing_account
	2. 对于匹配到的银行流水 Journal Entry (je_names), 把它们除了银行行以外的那一行
	   (即 counter-side, 一般是其他应付款/应收账款等) 的 account 也改成 clearing_account
	3. 同步 tabJournal Entry Account 子表

	两边都打进 clearing 后, clearing 借贷相抵接近零, 残余即未匹配的历史债项.

	参数:
		je_names_json:       JSON 数组, 待改写的银行流水 JE name 列表
		clearing_account:    清算账户全名 (如 "11215 - 票据清算中 - 台州京泰")
		bank_accounts_json:  JSON 数组, 银行子账户全名列表, 用于筛选 counter-side
	"""
	if "System Manager" not in frappe.get_roles(frappe.session.user) and frappe.session.user != "Administrator":
		frappe.throw(_("Only System Manager or Administrator can run this"))

	je_names = frappe.parse_json(je_names_json) if isinstance(je_names_json, str) else je_names_json
	bank_accounts = frappe.parse_json(bank_accounts_json) if isinstance(bank_accounts_json, str) else bank_accounts_json

	# 校验 clearing_account 存在且非 group
	target = frappe.db.get_value("Account", clearing_account, ["is_group"], as_dict=True)
	if not target:
		frappe.throw(f"Clearing account {clearing_account} not found")
	if target.is_group:
		frappe.throw(f"Clearing account {clearing_account} is a group")

	counts = {}

	# Step 1: acceptance 侧 (Bill Discount/Payment 产生的 GL, 当前在银行子账户)
	bank_placeholders = ",".join(["%s"] * len(bank_accounts))
	r = frappe.db.sql(
		f"""
		UPDATE `tabGL Entry`
		SET account=%s
		WHERE voucher_type IN ('Bill Discount', 'Bill Payment')
		  AND is_cancelled=0
		  AND account IN ({bank_placeholders})
		""",
		(clearing_account, *bank_accounts),
	)
	counts["acceptance_gl_moved"] = frappe.db.sql("SELECT ROW_COUNT()")[0][0]

	# Step 2: 银行流水 JE 的 counter-side
	if je_names:
		je_placeholders = ",".join(["%s"] * len(je_names))
		bank_placeholders = ",".join(["%s"] * len(bank_accounts))

		# 2a. tabGL Entry: 找每个 JE 里 account NOT IN bank_accounts 的那一行
		frappe.db.sql(
			f"""
			UPDATE `tabGL Entry`
			SET account=%s
			WHERE voucher_type='Journal Entry'
			  AND voucher_no IN ({je_placeholders})
			  AND account NOT IN ({bank_placeholders})
			  AND is_cancelled=0
			""",
			(clearing_account, *je_names, *bank_accounts),
		)
		counts["je_counter_gl_moved"] = frappe.db.sql("SELECT ROW_COUNT()")[0][0]

		# 2b. tabJournal Entry Account 子表同步
		frappe.db.sql(
			f"""
			UPDATE `tabJournal Entry Account`
			SET account=%s
			WHERE parent IN ({je_placeholders})
			  AND account NOT IN ({bank_placeholders})
			""",
			(clearing_account, *je_names, *bank_accounts),
		)
		counts["je_counter_child_moved"] = frappe.db.sql("SELECT ROW_COUNT()")[0][0]

		# 2c. 清 party_type/party 字段 - counter side 原本可能挂了 Customer/Supplier party,
		#     改到清算账户后这些 party 字段应该清空 (clearing 不是 Receivable/Payable type)
		frappe.db.sql(
			f"""
			UPDATE `tabGL Entry`
			SET party_type=NULL, party=NULL
			WHERE voucher_type='Journal Entry'
			  AND voucher_no IN ({je_placeholders})
			  AND account=%s
			  AND is_cancelled=0
			""",
			(*je_names, clearing_account),
		)
		frappe.db.sql(
			f"""
			UPDATE `tabJournal Entry Account`
			SET party_type=NULL, party=NULL
			WHERE parent IN ({je_placeholders})
			  AND account=%s
			""",
			(*je_names, clearing_account),
		)

	frappe.db.commit()

	# 汇报 clearing 账户余额
	bal = frappe.db.sql(
		"SELECT SUM(debit) as dr, SUM(credit) as cr, SUM(debit - credit) as net FROM `tabGL Entry` WHERE account=%s AND is_cancelled=0",
		(clearing_account,),
		as_dict=True,
	)[0]
	counts["clearing_balance"] = {
		"debit_total": float(bal.dr or 0),
		"credit_total": float(bal.cr or 0),
		"net_debit": float(bal.net or 0),
	}
	return counts


@frappe.whitelist()
def purge_bank_account(account_name, delete_account=False):
	"""清空某银行账户上的所有 JE/GL/PLE, 可选删除账户本身.

	用于期初迭代中整体丢弃某个银行的所有数据, 重新开始.

	步骤:
	1. 找到所有在该 account 上留有 GL Entry 的 Journal Entry (voucher_no)
	2. SQL 删除:
	   - tabGL Entry (所有该 voucher_no 的条目)
	   - tabPayment Ledger Entry (voucher_type=Journal Entry, voucher_no in list)
	   - tabJournal Entry Account (parent in list)
	   - tabJournal Entry (name in list)
	3. 还要删该 account 自己残留的 GL Entry (例如 Bill Discount/Payment 直接生成的)
	4. 若 delete_account=True, 删除 tabAccount 记录 (前提: 叶子账户, 已无 GL)

	delete_account: 字符串 "1"/"true" 或 bool, 默认不删
	"""
	if "System Manager" not in frappe.get_roles(frappe.session.user) and frappe.session.user != "Administrator":
		frappe.throw(_("Only System Manager or Administrator can run this"))

	if isinstance(delete_account, str):
		delete_account = delete_account.lower() in ("1", "true", "yes")

	# 1. 找 JE 列表
	je_rows = frappe.db.sql(
		"SELECT DISTINCT voucher_no FROM `tabGL Entry` WHERE account=%s AND voucher_type='Journal Entry'",
		(account_name,),
	)
	je_names = [r[0] for r in je_rows]

	counts = {"account": account_name, "journal_entries_found": len(je_names)}

	if je_names:
		placeholders = ",".join(["%s"] * len(je_names))
		# GL Entry (全部 voucher_no 相关)
		frappe.db.sql(
			f"DELETE FROM `tabGL Entry` WHERE voucher_type='Journal Entry' AND voucher_no IN ({placeholders})",
			tuple(je_names),
		)
		# Payment Ledger Entry
		frappe.db.sql(
			f"DELETE FROM `tabPayment Ledger Entry` WHERE voucher_type='Journal Entry' AND voucher_no IN ({placeholders})",
			tuple(je_names),
		)
		# JE Account 子表
		frappe.db.sql(
			f"DELETE FROM `tabJournal Entry Account` WHERE parent IN ({placeholders})",
			tuple(je_names),
		)
		# JE 本体
		frappe.db.sql(
			f"DELETE FROM `tabJournal Entry` WHERE name IN ({placeholders})",
			tuple(je_names),
		)
		counts["deleted_je"] = len(je_names)

	# 2. 账户自身残留 GL (例如 Bill Discount/Payment 直接生成的, voucher_type != Journal Entry)
	r = frappe.db.sql(
		"DELETE FROM `tabGL Entry` WHERE account=%s",
		(account_name,),
	)
	counts["deleted_residual_gl"] = frappe.db.sql("SELECT ROW_COUNT()")[0][0]

	# 3. 删除账户本身
	if delete_account:
		remaining = frappe.db.sql(
			"SELECT COUNT(*) FROM `tabGL Entry` WHERE account=%s",
			(account_name,),
		)[0][0]
		if remaining > 0:
			frappe.throw(f"Account {account_name} still has {remaining} GL entries after purge")
		frappe.db.sql("DELETE FROM `tabAccount` WHERE name=%s", (account_name,))
		counts["account_deleted"] = True
		frappe.clear_document_cache("Account", account_name)

	frappe.db.commit()
	return counts


@frappe.whitelist()
def purge_cancelled_and_draft_je(cheque_no_like=None):
	"""清理 docstatus=2 (cancelled) 和 docstatus=0 (draft) 的 Journal Entry.

	可选 cheque_no_like 做前缀过滤 (比如 "F(B)-%"), 只清理导入相关的.
	不传则清全部 (慎用).

	会删:
	- tabJournal Entry (name in list)
	- tabJournal Entry Account (parent in list)
	- tabGL Entry (is_cancelled=1 且 voucher_no in list) - cancel 后留下的影子条目
	- tabPayment Ledger Entry 同上
	"""
	if "System Manager" not in frappe.get_roles(frappe.session.user) and frappe.session.user != "Administrator":
		frappe.throw(_("Only System Manager or Administrator can run this"))

	if cheque_no_like:
		rows = frappe.db.sql(
			"SELECT name FROM `tabJournal Entry` WHERE docstatus IN (0, 2) AND cheque_no LIKE %s",
			(cheque_no_like,),
		)
	else:
		rows = frappe.db.sql(
			"SELECT name FROM `tabJournal Entry` WHERE docstatus IN (0, 2)",
		)
	je_names = [r[0] for r in rows]

	counts = {"found": len(je_names)}

	if je_names:
		placeholders = ",".join(["%s"] * len(je_names))
		frappe.db.sql(
			f"DELETE FROM `tabGL Entry` WHERE voucher_type='Journal Entry' AND voucher_no IN ({placeholders})",
			tuple(je_names),
		)
		frappe.db.sql(
			f"DELETE FROM `tabPayment Ledger Entry` WHERE voucher_type='Journal Entry' AND voucher_no IN ({placeholders})",
			tuple(je_names),
		)
		frappe.db.sql(
			f"DELETE FROM `tabJournal Entry Account` WHERE parent IN ({placeholders})",
			tuple(je_names),
		)
		frappe.db.sql(
			f"DELETE FROM `tabJournal Entry` WHERE name IN ({placeholders})",
			tuple(je_names),
		)
		counts["deleted"] = len(je_names)

	frappe.db.commit()
	return counts


# ---------------------------------------------------------------------------
# 宁波银行"借壳供应商"历史数据正规化
# ---------------------------------------------------------------------------
#
# 背景:
#   老 ERP 不支持电子承兑贴现/到期兑付业务, 临时把"宁波银行"注册成供应商, 把实际
#   收到的贴现款/到期兑付款硬记成"银行(10022)/ 应付账款-结算(party=宁波银行)",
#   以双边账的形式平账. 从会计语义看完全错误: 收到承兑兑付应该冲减应收票据, 收到
#   贴现款应该冲减应收票据并计提贴现利息, 都跟"应付账款/宁波银行"没任何关系.
#
#   acceptance app 上线后, Bill of Exchange 已经逐张建好, 甚至 bill_status 被期初
#   脚本直接 SQL 写成了 Discounted/Settled, 但底下的会计凭证还是老旧的假应付. 本
#   迁移工具负责:
#     1. 把 32 笔"贴现收入"JE 重建为真正的 Bill Discount 单据
#     2. 把 3 笔"电子商业汇票到期收款"JE 重建为真正的 Bill Payment 单据
#     3. 把 10 笔"金额修正: 收支/金额错误"的孤儿 FIX 条目迁移到 11215 票据清算中,
#        清空 party, 这些是导入期的账务调整不是真实票据业务, 但为了能删 supplier
#        必须解除它们对宁波银行的 party 引用
#     4. 最后删除 Supplier "SUP-2070" 与 "宁波银行"
#
#   幂等: 处理过的 JE 已经不存在或不再关联宁波银行 party, 重跑会跳过.
# ---------------------------------------------------------------------------

_NINGBO_SUPPLIERS = ("SUP-2070", "宁波银行")
_BANK_ACCOUNT = "10022 - 京泰宁波 - 台州京泰"
_NR_ACCOUNT = "11211 - 应收票据 - 台州京泰"
_INTEREST_ACCOUNT = "财务费用_票据贴现利息 - 台州京泰"
_CLEARING_ACCOUNT = "11215 - 票据清算中 - 台州京泰"
_PAYABLE_SETTLEMENT = "22021 - 应付账款-结算 - 台州京泰"
_COMPANY = "台州京泰电气有限公司"

# 贴现 remarks 示例:
#   "... 备注 贴现收入，票号：531845200001420240723000165421 000008261001,000011300000"
_DISCOUNT_RE = re.compile(r"贴现收入[，,]\s*票号[：:]\s*(\d{30})\s+(\d{12})[，,](\d{12})")

# 到期兑付 remarks 示例:
#   "... 备注 电子商业汇票到期收款。票号：131011000011020210816000939728"
_PAYMENT_RE = re.compile(r"电子商业汇票到期收款[。.]\s*票号[：:]\s*(\d{30})")

_FIX_KEYWORD = "金额修正"
_BILL_NO_IN_TEXT_RE = re.compile(r"(?<!\d)(\d{30})(?!\d)")
_AMOUNT_TOLERANCE = Decimal("0.01")


def _require_admin():
	if "System Manager" not in frappe.get_roles(frappe.session.user) and frappe.session.user != "Administrator":
		frappe.throw(_("Only System Manager or Administrator can run this"))


def _classify_remarks(remarks):
	"""根据 GL Entry remarks 返回 (kind, bill_no).

	kind ∈ {"discount", "payment", "fix", None}
	"""
	if not remarks:
		return (None, None)
	if _FIX_KEYWORD in remarks:
		return ("fix", None)
	m = _DISCOUNT_RE.search(remarks)
	if m:
		return ("discount", m.group(1))
	m = _PAYMENT_RE.search(remarks)
	if m:
		return ("payment", m.group(1))
	return (None, None)


def _parse_flag(value, default=False):
	"""把 query string / JSON 里的布尔值统一转成 bool."""
	if value is None:
		return default
	if isinstance(value, bool):
		return value
	if isinstance(value, (int, float)):
		return bool(value)
	return str(value).strip().lower() not in ("", "0", "false", "no", "off")


def _normalize_year(year):
	"""把 year 参数规范成 int 或 None."""
	if year in (None, "", "all", "ALL"):
		return None
	try:
		year = int(str(year).strip())
	except (TypeError, ValueError):
		frappe.throw(_("Invalid year: {0}").format(year))
	if year < 2000 or year > 2100:
		frappe.throw(_("Year out of range: {0}").format(year))
	return year


def _to_decimal_2(value):
	"""把金额安全转成两位小数 Decimal."""
	try:
		return Decimal(str(value or 0)).quantize(Decimal("0.01"))
	except (InvalidOperation, ValueError, TypeError):
		return Decimal("0.00")


def _extract_bill_no(text):
	"""从 remarks / user_remark 里抓第一段 30 位票号."""
	if not text:
		return None
	m = _BILL_NO_IN_TEXT_RE.search(text)
	return m.group(1) if m else None


def _short_text(text, limit=120):
	"""压缩多行 remarks, 便于 CSV 预览."""
	text = (text or "").replace("\r", " ").replace("\n", " ").strip()
	if len(text) <= limit:
		return text
	return text[: max(limit - 3, 0)] + "..."


def _csv_from_rows(rows, columns):
	"""把行列表编码成 CSV 字符串, 方便前端直接下载."""
	buf = io.StringIO()
	writer = csv.DictWriter(buf, fieldnames=columns, lineterminator="\n")
	writer.writeheader()
	for row in rows:
		writer.writerow({col: row.get(col, "") for col in columns})
	return buf.getvalue()


def _date_gap_days(left, right):
	"""日期差用于匹配时打破平局."""
	if isinstance(left, date) and isinstance(right, date):
		return abs((left - right).days)
	return 999999


def _pair_clearing_rows(dr_rows, cr_rows):
	"""按 票号 + 金额(±0.01) 配对清算中借贷行."""
	cr_groups = defaultdict(list)
	for row in cr_rows:
		row["_matched"] = False
		cr_groups[row["bill_no"]].append(row)

	for rows in cr_groups.values():
		rows.sort(key=lambda d: (d["posting_date"], d["amount"], d["je_name"], d["gl_name"]))

	dr_rows = sorted(dr_rows, key=lambda d: (d["posting_date"], d["amount"], d["voucher_type"], d["doc_name"]))
	matched = []
	dr_unmatched = []

	for dr in dr_rows:
		candidates = cr_groups.get(dr["bill_no"], [])
		best = None
		best_key = None
		for candidate in candidates:
			if candidate["_matched"]:
				continue
			diff = abs(dr["amount"] - candidate["amount"])
			if diff > _AMOUNT_TOLERANCE:
				continue
			key = (
				diff,
				_date_gap_days(dr["posting_date"], candidate["posting_date"]),
				candidate["posting_date"],
				candidate["je_name"],
			)
			if best is None or key < best_key:
				best = candidate
				best_key = key

		if not best:
			dr_unmatched.append(dr)
			continue

		best["_matched"] = True
		matched.append({
			"bill_no": dr["bill_no"],
			"金额": float(dr["amount"]),
			"Dr日期": str(dr["posting_date"]),
			"Cr日期": str(best["posting_date"]),
			"Dr单据": dr["doc_name"],
			"Dr单据类型": dr["voucher_type"],
			"Cr凭证": best["je_name"],
			"金额差": float(abs(dr["amount"] - best["amount"])),
			"Cr备注摘要": best["remarks_summary"],
		})

	cr_unmatched = []
	for rows in cr_groups.values():
		for row in rows:
			if not row["_matched"]:
				cr_unmatched.append(row)

	cr_unmatched.sort(key=lambda d: (d["posting_date"], d["amount"], d["je_name"], d["gl_name"]))
	return matched, dr_unmatched, cr_unmatched


@frappe.whitelist()
def inspect_clearing_imbalance_by_bill_no(year=None, output_csv=True):
	"""按票号精确诊断 11215 清算中账户的不平衡来源.

	规则:
	1. Dr 侧仅看 Bill Discount / Bill Payment 在 11215 上的借方行，并回溯到 BoE.bill_no
	2. Cr 侧仅看 Journal Entry 在 11215 上的贷方行，并从 JE.user_remark / GL.remarks 提取 30 位票号
	3. 按 bill_no + 金额(±0.01) 配对；同票号多条时优先金额差最小、日期最近
	"""
	_require_admin()
	year = _normalize_year(year)
	output_csv = _parse_flag(output_csv, default=True)

	filters = {"clearing_account": _CLEARING_ACCOUNT}
	date_filter_sql = ""
	if year:
		filters["from_date"] = f"{year}-01-01"
		filters["to_date"] = f"{year + 1}-01-01"
		date_filter_sql = " AND gl.posting_date >= %(from_date)s AND gl.posting_date < %(to_date)s"

	dr_rows = frappe.db.sql(
		f"""
		SELECT
			gl.name AS gl_name,
			gl.posting_date,
			gl.voucher_type,
			gl.voucher_no AS doc_name,
			gl.debit AS amount,
			bd.bill_of_exchange,
			boe.bill_no
		FROM `tabGL Entry` gl
		INNER JOIN `tabBill Discount` bd
			ON gl.voucher_type='Bill Discount'
		   AND bd.name=gl.voucher_no
		LEFT JOIN `tabBill of Exchange` boe
			ON boe.name=bd.bill_of_exchange
		WHERE gl.account=%(clearing_account)s
		  AND gl.is_cancelled=0
		  AND gl.debit > 0
		  AND bd.docstatus=1
		  {date_filter_sql}

		UNION ALL

		SELECT
			gl.name AS gl_name,
			gl.posting_date,
			gl.voucher_type,
			gl.voucher_no AS doc_name,
			gl.debit AS amount,
			bp.bill_of_exchange,
			boe.bill_no
		FROM `tabGL Entry` gl
		INNER JOIN `tabBill Payment` bp
			ON gl.voucher_type='Bill Payment'
		   AND bp.name=gl.voucher_no
		LEFT JOIN `tabBill of Exchange` boe
			ON boe.name=bp.bill_of_exchange
		WHERE gl.account=%(clearing_account)s
		  AND gl.is_cancelled=0
		  AND gl.debit > 0
		  AND bp.docstatus=1
		  {date_filter_sql}

		ORDER BY posting_date, voucher_type, doc_name
		""",
		filters,
		as_dict=True,
	)

	cr_gl_rows = frappe.db.sql(
		f"""
		SELECT
			gl.name AS gl_name,
			gl.posting_date,
			gl.voucher_no AS je_name,
			gl.credit AS amount,
			je.user_remark,
			gl.remarks
		FROM `tabGL Entry` gl
		INNER JOIN `tabJournal Entry` je
			ON je.name=gl.voucher_no
		WHERE gl.account=%(clearing_account)s
		  AND gl.voucher_type='Journal Entry'
		  AND gl.is_cancelled=0
		  AND gl.credit > 0
		  AND je.docstatus=1
		  {date_filter_sql}
		ORDER BY gl.posting_date, gl.voucher_no, gl.name
		""",
		filters,
		as_dict=True,
	)

	dr_items = []
	dr_missing_bill_no = []
	for row in dr_rows:
		item = {
			"bill_no": (row.get("bill_no") or "").strip(),
			"amount": _to_decimal_2(row.get("amount")),
			"posting_date": row.get("posting_date"),
			"voucher_type": row.get("voucher_type"),
			"doc_name": row.get("doc_name"),
			"bill_of_exchange": row.get("bill_of_exchange"),
			"gl_name": row.get("gl_name"),
		}
		if item["bill_no"]:
			dr_items.append(item)
		else:
			dr_missing_bill_no.append({
				"日期": str(item["posting_date"]),
				"金额": float(item["amount"]),
				"单据类型": item["voucher_type"],
				"单据名": item["doc_name"],
				"票据": item["bill_of_exchange"] or "",
				"GL": item["gl_name"],
			})

	cr_items = []
	cr_missing_bill_no = []
	for row in cr_gl_rows:
		user_remark = (row.get("user_remark") or "").strip()
		gl_remarks = (row.get("remarks") or "").strip()
		source_text = user_remark or gl_remarks
		item = {
			"bill_no": _extract_bill_no(user_remark) or _extract_bill_no(gl_remarks),
			"amount": _to_decimal_2(row.get("amount")),
			"posting_date": row.get("posting_date"),
			"je_name": row.get("je_name"),
			"gl_name": row.get("gl_name"),
			"remarks_summary": _short_text(source_text),
		}
		if item["bill_no"]:
			cr_items.append(item)
		else:
			cr_missing_bill_no.append({
				"日期": str(item["posting_date"]),
				"金额": float(item["amount"]),
				"JE名": item["je_name"],
				"GL": item["gl_name"],
				"remarks摘要": item["remarks_summary"],
			})

	matched_rows, dr_unmatched_items, cr_unmatched_items = _pair_clearing_rows(dr_items, cr_items)

	dr_unmatched_csv_rows = [
		{
			"票号": row["bill_no"],
			"金额": float(row["amount"]),
			"日期": str(row["posting_date"]),
			"单据类型": row["voucher_type"],
			"单据名": row["doc_name"],
			"票据": row["bill_of_exchange"] or "",
		}
		for row in dr_unmatched_items
	]
	cr_unmatched_csv_rows = [
		{
			"票号": row["bill_no"],
			"金额": float(row["amount"]),
			"日期": str(row["posting_date"]),
			"JE名": row["je_name"],
			"remarks摘要": row["remarks_summary"],
		}
		for row in cr_unmatched_items
	]

	result = {
		"year": year,
		"clearing_account": _CLEARING_ACCOUNT,
		"dr_rows_in_scope": len(dr_items),
		"cr_rows_in_scope": len(cr_items),
		"matched_pairs": len(matched_rows),
		"matched_amount": round(sum(row["金额"] for row in matched_rows), 2),
		"dr_unmatched_count": len(dr_unmatched_csv_rows),
		"dr_unmatched_amount": round(sum(row["金额"] for row in dr_unmatched_csv_rows), 2),
		"cr_unmatched_count": len(cr_unmatched_csv_rows),
		"cr_unmatched_amount": round(sum(row["金额"] for row in cr_unmatched_csv_rows), 2),
		"dr_missing_bill_no_count": len(dr_missing_bill_no),
		"dr_missing_bill_no_amount": round(sum(row["金额"] for row in dr_missing_bill_no), 2),
		"cr_missing_bill_no_count": len(cr_missing_bill_no),
		"cr_missing_bill_no_amount": round(sum(row["金额"] for row in cr_missing_bill_no), 2),
		"preview": {
			"matched": matched_rows[:20],
			"dr_unmatched": dr_unmatched_csv_rows[:50],
			"cr_unmatched": cr_unmatched_csv_rows[:50],
			"dr_missing_bill_no": dr_missing_bill_no[:20],
			"cr_missing_bill_no": cr_missing_bill_no[:20],
		},
	}

	if output_csv:
		suffix = str(year) if year else "all"
		result["csv"] = {
			"dr_unmatched_filename": f"clearing_dr_unmatched_{suffix}.csv",
			"dr_unmatched": _csv_from_rows(
				dr_unmatched_csv_rows,
				["票号", "金额", "日期", "单据类型", "单据名", "票据"],
			),
			"cr_unmatched_filename": f"clearing_cr_unmatched_{suffix}.csv",
			"cr_unmatched": _csv_from_rows(
				cr_unmatched_csv_rows,
				["票号", "金额", "日期", "JE名", "remarks摘要"],
			),
		}

	return result


@frappe.whitelist()
def annotate_clearing_bank_journal_bill_no(annotations_json, dry_run=1):
	"""给已存在的银行流水 JE 补充完整票号到 user_remark.

	仅更新文字说明，不改金额、不改会计分录。适用于历史导入时 remarks 里只有
	20 位票号前缀、导致精确诊断工具抓不到 bill_no 的场景。

	annotations_json: JSON 数组，每项至少包含:
	- je: Journal Entry.name
	- bill_no: 30 位票号
	可选:
	- source: 说明来源，如 "prefix-match"
	"""
	_require_admin()
	if isinstance(dry_run, str):
		dry_run = dry_run.lower() not in ("0", "false", "no", "")

	annotations = frappe.parse_json(annotations_json) if isinstance(annotations_json, str) else annotations_json
	if not annotations:
		return {"dry_run": dry_run, "updated": 0, "skipped": 0, "plan": []}

	plan = []
	seen = set()
	for item in annotations:
		je_name = (item.get("je") or item.get("je_name") or "").strip()
		bill_no = (item.get("bill_no") or "").strip()
		source = (item.get("source") or "manual").strip()
		if not je_name or not bill_no:
			continue
		key = (je_name, bill_no)
		if key in seen:
			continue
		seen.add(key)

		row = frappe.db.get_value(
			"Journal Entry",
			je_name,
			["name", "docstatus", "user_remark"],
			as_dict=True,
		)
		if not row:
			plan.append({"je": je_name, "bill_no": bill_no, "source": source, "action": "skip", "reason": "JE not found"})
			continue
		if row.docstatus != 1:
			plan.append({"je": je_name, "bill_no": bill_no, "source": source, "action": "skip", "reason": f"docstatus={row.docstatus}"})
			continue

		current = (row.user_remark or "").strip()
		existing_bill_no = _extract_bill_no(current)
		if existing_bill_no == bill_no:
			plan.append({"je": je_name, "bill_no": bill_no, "source": source, "action": "skip", "reason": "already annotated"})
			continue
		if existing_bill_no and existing_bill_no != bill_no:
			plan.append({
				"je": je_name,
				"bill_no": bill_no,
				"source": source,
				"action": "skip",
				"reason": f"user_remark already has different bill_no={existing_bill_no}",
			})
			continue

		note = f"自动补标票号：{bill_no}"
		new_remark = f"{current} | {note}" if current else note
		plan.append({
			"je": je_name,
			"bill_no": bill_no,
			"source": source,
			"action": "update",
			"from": current,
			"to": new_remark,
		})

	if dry_run:
		return {
			"dry_run": True,
			"update_count": len([x for x in plan if x["action"] == "update"]),
			"skip_count": len([x for x in plan if x["action"] == "skip"]),
			"plan": plan,
		}

	updated = 0
	for item in plan:
		if item["action"] != "update":
			continue
		frappe.db.sql(
			"UPDATE `tabJournal Entry` SET user_remark=%s WHERE name=%s",
			(item["to"], item["je"]),
		)
		frappe.clear_document_cache("Journal Entry", item["je"])
		updated += 1

	frappe.db.commit()
	return {
		"dry_run": False,
		"updated": updated,
		"skipped": len([x for x in plan if x["action"] == "skip"]),
		"plan": plan,
	}


def _resolve_restore_target_from_bank_against(bank_against, title=None, pay_to_recd_from=None):
	"""根据银行侧残留 against_account 反推误迁移 JE 应恢复到的对方科目.

	优先级:
	1. against_account 本身就是合法总账科目 -> 直接恢复到该科目
	2. against_account 是 Customer.name -> 恢复到应收账款并回填 party
	3. against_account 是 Supplier.name -> 恢复到应付账款并回填 party

	仅返回"可无歧义恢复"的结果；否则返回 (None, reason).
	"""
	bank_against = (bank_against or "").strip()
	if not bank_against:
		return None, "bank against_account 为空"

	account_row = frappe.db.get_value(
		"Account",
		bank_against,
		["name", "is_group"],
		as_dict=True,
	)
	if account_row:
		if account_row.is_group:
			return None, f"against_account={bank_against} 是 group 科目"
		return {
			"account": account_row.name,
			"party_type": None,
			"party": None,
			"source": "account",
			"matched_name": bank_against,
		}, f"按原 against_account 恢复为科目 {bank_against}"

	counterparty = (pay_to_recd_from or title or "").strip()
	customer_row = frappe.db.get_value(
		"Customer",
		bank_against,
		["name", "customer_name", "default_receivable_account"],
		as_dict=True,
	)
	if customer_row:
		if counterparty and counterparty not in (customer_row.customer_name, customer_row.name):
			return None, (
				f"Customer {customer_row.name} 名称不匹配: "
				f"counterparty={counterparty}, customer_name={customer_row.customer_name}"
			)
		target_account = customer_row.default_receivable_account or frappe.db.get_value(
			"Company", _COMPANY, "default_receivable_account"
		)
		if not target_account:
			return None, f"Customer {customer_row.name} 没有可用应收科目"
		target_account_row = frappe.db.get_value("Account", target_account, ["name", "is_group"], as_dict=True)
		if not target_account_row or target_account_row.is_group:
			return None, f"Customer {customer_row.name} 的应收科目 {target_account} 非法"
		return {
			"account": target_account_row.name,
			"party_type": "Customer",
			"party": customer_row.name,
			"source": "customer",
			"matched_name": customer_row.customer_name or customer_row.name,
		}, f"按 Customer {customer_row.name} 恢复到 {target_account_row.name}"

	supplier_row = frappe.db.get_value(
		"Supplier",
		bank_against,
		["name", "supplier_name", "default_payable_account"],
		as_dict=True,
	)
	if supplier_row:
		if counterparty and counterparty not in (supplier_row.supplier_name, supplier_row.name):
			return None, (
				f"Supplier {supplier_row.name} 名称不匹配: "
				f"counterparty={counterparty}, supplier_name={supplier_row.supplier_name}"
			)
		target_account = (
			supplier_row.default_payable_account
			or frappe.db.get_value("Company", _COMPANY, "default_payable_account")
			or _PAYABLE_SETTLEMENT
		)
		if not target_account:
			return None, f"Supplier {supplier_row.name} 没有可用应付科目"
		target_account_row = frappe.db.get_value("Account", target_account, ["name", "is_group"], as_dict=True)
		if not target_account_row or target_account_row.is_group:
			return None, f"Supplier {supplier_row.name} 的应付科目 {target_account} 非法"
		return {
			"account": target_account_row.name,
			"party_type": "Supplier",
			"party": supplier_row.name,
			"source": "supplier",
			"matched_name": supplier_row.supplier_name or supplier_row.name,
		}, f"按 Supplier {supplier_row.name} 恢复到 {target_account_row.name}"

	return None, f"against_account={bank_against} 既不是科目也不是客户/供应商"


@frappe.whitelist()
def restore_clearing_bank_journal_counter_from_bank_against(je_names_json, dry_run=1):
	"""把误迁移到 11215 的银行流水 JE 对方科目恢复回原始 against_account 所指向的对象.

	使用场景:
	- 历史 `migrate_bill_bank_to_clearing` 把普通银行回款/杂项入账一并迁进了 11215
	- 但银行侧分录的 against_account 仍残留了原始科目/客户/供应商线索
	- 本函数仅对"可无歧义恢复"的 JE 生效

	参数:
	- je_names_json: JSON 数组，Journal Entry.name 列表
	- dry_run: 默认 1，仅输出恢复计划
	"""
	_require_admin()
	dry_run = _parse_flag(dry_run, default=True)
	je_names = frappe.parse_json(je_names_json) if isinstance(je_names_json, str) else je_names_json
	je_names = [str(name).strip() for name in (je_names or []) if str(name or "").strip()]
	if not je_names:
		return {"dry_run": dry_run, "updated": 0, "skipped": 0, "plan": []}

	plan = []
	seen = set()
	for je_name in je_names:
		if je_name in seen:
			continue
		seen.add(je_name)

		je = frappe.db.get_value(
			"Journal Entry",
			je_name,
			["name", "docstatus", "posting_date", "title", "pay_to_recd_from", "user_remark", "cheque_no"],
			as_dict=True,
		)
		if not je:
			plan.append({"je": je_name, "action": "skip", "reason": "JE 不存在"})
			continue
		if je.docstatus != 1:
			plan.append({"je": je_name, "action": "skip", "reason": f"docstatus={je.docstatus}"})
			continue
		if _extract_bill_no(je.user_remark):
			plan.append({"je": je_name, "action": "skip", "reason": "user_remark 已带票号，不做恢复"})
			continue

		child_rows = frappe.db.sql(
			"""
			SELECT
				name, idx, account, debit, credit, party_type, party, against_account
			FROM `tabJournal Entry Account`
			WHERE parent=%s
			ORDER BY idx
			""",
			(je_name,),
			as_dict=True,
		)
		gl_rows = frappe.db.sql(
			"""
			SELECT
				name, account, debit, credit, party_type, party, against
			FROM `tabGL Entry`
			WHERE voucher_type='Journal Entry'
			  AND voucher_no=%s
			  AND is_cancelled=0
			ORDER BY creation, name
			""",
			(je_name,),
			as_dict=True,
		)
		bank_child = next((row for row in child_rows if float(row.debit or 0) > 0 and row.account != _CLEARING_ACCOUNT), None)
		counter_child = next((row for row in child_rows if float(row.credit or 0) > 0 and row.account != (bank_child.account if bank_child else None)), None)
		bank_gl = next((row for row in gl_rows if float(row.debit or 0) > 0 and row.account == (bank_child.account if bank_child else None)), None)
		counter_gl = next((row for row in gl_rows if float(row.credit or 0) > 0 and row.account == (counter_child.account if counter_child else None)), None)

		if not bank_child or not counter_child or not bank_gl or not counter_gl:
			plan.append({
				"je": je_name,
				"action": "skip",
				"reason": "无法唯一定位 bank/counter 分录",
			})
			continue

		target, reason = _resolve_restore_target_from_bank_against(
			bank_child.against_account,
			title=je.title,
			pay_to_recd_from=je.pay_to_recd_from,
		)
		if not target:
			plan.append({
				"je": je_name,
				"action": "skip",
				"reason": reason,
				"bank_account": bank_child.account,
				"bank_against": bank_child.against_account,
				"title": je.title,
				"pay_to_recd_from": je.pay_to_recd_from,
			})
			continue

		current_party_type = counter_child.party_type or None
		current_party = counter_child.party or None
		if (
			counter_child.account == target["account"]
			and current_party_type == target["party_type"]
			and current_party == target["party"]
		):
			plan.append({
				"je": je_name,
				"action": "skip",
				"reason": "已经恢复完成",
				"from_account": counter_child.account,
				"to_account": target["account"],
			})
			continue

		if counter_child.account != _CLEARING_ACCOUNT:
			plan.append({
				"je": je_name,
				"action": "skip",
				"reason": f"counter 科目当前不是 {_CLEARING_ACCOUNT}: {counter_child.account}",
				"bank_account": bank_child.account,
				"bank_against": bank_child.against_account,
			})
			continue

		plan.append({
			"je": je_name,
			"action": "update",
			"posting_date": str(je.posting_date),
			"amount": float(counter_child.credit or 0),
			"cheque_no": je.cheque_no,
			"title": je.title,
			"pay_to_recd_from": je.pay_to_recd_from,
			"user_remark": _short_text(je.user_remark, 160),
			"bank_account": bank_child.account,
			"bank_against": bank_child.against_account,
			"source": target["source"],
			"matched_name": target["matched_name"],
			"from_account": counter_child.account,
			"to_account": target["account"],
			"to_party_type": target["party_type"],
			"to_party": target["party"],
			"child_row": counter_child.name,
			"gl_row": counter_gl.name,
			"reason": reason,
		})

	if dry_run:
		return {
			"dry_run": True,
			"update_count": len([item for item in plan if item["action"] == "update"]),
			"skip_count": len([item for item in plan if item["action"] == "skip"]),
			"total_amount": round(sum(item.get("amount", 0) for item in plan if item["action"] == "update"), 2),
			"plan": plan,
		}

	updated = []
	skipped = []
	for item in plan:
		if item["action"] != "update":
			skipped.append(item)
			continue

		frappe.db.sql(
			"""
			UPDATE `tabJournal Entry Account`
			SET account=%s, party_type=%s, party=%s
			WHERE name=%s
			""",
			(item["to_account"], item["to_party_type"], item["to_party"], item["child_row"]),
		)
		frappe.db.sql(
			"""
			UPDATE `tabGL Entry`
			SET account=%s, party_type=%s, party=%s
			WHERE name=%s
			""",
			(item["to_account"], item["to_party_type"], item["to_party"], item["gl_row"]),
		)
		frappe.clear_document_cache("Journal Entry", item["je"])
		updated.append({
			"je": item["je"],
			"amount": item["amount"],
			"from_account": item["from_account"],
			"to_account": item["to_account"],
			"to_party_type": item["to_party_type"],
			"to_party": item["to_party"],
			"reason": item["reason"],
		})

	frappe.db.commit()
	return {
		"dry_run": False,
		"updated_count": len(updated),
		"skipped_count": len(skipped),
		"total_amount": round(sum(item["amount"] for item in updated), 2),
		"updated": updated,
		"skipped": skipped,
	}


def _allocate_proportional(boes, total_actual, total_interest):
	"""按 face 比例把 total_actual 和 total_interest 分摊到每个 BoE.

	返回 [(boe_dict, alloc_actual, alloc_interest), ...], 最后一条吸收 2 位小数舍入差.
	单条 BoE 的情况直接全额分配.
	"""
	n = len(boes)
	if n == 1:
		return [(boes[0], round(total_actual, 2), round(total_interest, 2))]

	total_face = sum(b["face"] for b in boes)
	allocs = []
	acc_actual = 0.0
	acc_interest = 0.0
	for i, b in enumerate(boes):
		if i < n - 1:
			ratio = b["face"] / total_face
			a = round(total_actual * ratio, 2)
			ii = round(total_interest * ratio, 2)
			acc_actual += a
			acc_interest += ii
			allocs.append((b, a, ii))
		else:
			# 末条吸收所有舍入差
			allocs.append((b, round(total_actual - acc_actual, 2), round(total_interest - acc_interest, 2)))
	return allocs


def _delete_je_completely(je_name):
	"""SQL 级别彻底删除一张 JE 及其所有伴生条目."""
	frappe.db.sql(
		"DELETE FROM `tabGL Entry` WHERE voucher_type='Journal Entry' AND voucher_no=%s",
		(je_name,),
	)
	frappe.db.sql(
		"DELETE FROM `tabPayment Ledger Entry` WHERE voucher_type='Journal Entry' AND voucher_no=%s",
		(je_name,),
	)
	frappe.db.sql(
		"DELETE FROM `tabJournal Entry Account` WHERE parent=%s",
		(je_name,),
	)
	frappe.db.sql(
		"DELETE FROM `tabJournal Entry` WHERE name=%s",
		(je_name,),
	)


@frappe.whitelist()
def inspect_ningbo_bank_supplier():
	"""只读诊断: 盘点所有 party=宁波银行/SUP-2070 的 GL 条目, 按语义分组.

	输出可以在前端 Network 面板直接看, 用于迁移前后双检.
	"""
	_require_admin()

	rows = frappe.db.sql(
		"""
		SELECT name, posting_date, voucher_no, debit, credit, account, remarks
		FROM `tabGL Entry`
		WHERE party_type='Supplier'
		  AND party IN %(parties)s
		  AND is_cancelled=0
		ORDER BY posting_date, voucher_no
		""",
		{"parties": _NINGBO_SUPPLIERS},
		as_dict=True,
	)

	groups = {"discount": [], "payment": [], "fix": [], "unknown": []}
	for r in rows:
		kind, bill_no = _classify_remarks(r["remarks"])
		item = {
			"gl": r["name"],
			"je": r["voucher_no"],
			"date": str(r["posting_date"]),
			"amount": float(r["credit"] or 0) - float(r["debit"] or 0),
			"bill_no": bill_no,
		}
		groups[kind or "unknown"].append(item)

	return {
		"total": len(rows),
		"discount_count": len(groups["discount"]),
		"payment_count": len(groups["payment"]),
		"fix_count": len(groups["fix"]),
		"unknown_count": len(groups["unknown"]),
		"groups": groups,
	}


@frappe.whitelist()
def migrate_ningbo_bank_supplier(dry_run=1):
	"""把宁波银行借壳供应商的所有 JE 正规化为 Bill Discount / Bill Payment.

	参数:
		dry_run: 默认 1 只打印动作计划不改库, 传 0 才真正执行.

	返回: 每一笔的处理结果明细, 便于核对.
	"""
	_require_admin()
	if isinstance(dry_run, str):
		dry_run = dry_run.lower() not in ("0", "false", "no", "")

	# 1. 拉取全部关联 GL (22021 应付账款侧)
	gl_rows = frappe.db.sql(
		"""
		SELECT gl.name AS gl_name, gl.voucher_no AS je_name, gl.posting_date,
		       gl.debit, gl.credit, gl.remarks,
		       je.cheque_no, je.user_remark
		FROM `tabGL Entry` gl
		JOIN `tabJournal Entry` je ON je.name = gl.voucher_no
		WHERE gl.party_type='Supplier'
		  AND gl.party IN %(parties)s
		  AND gl.is_cancelled=0
		ORDER BY gl.posting_date, gl.voucher_no
		""",
		{"parties": _NINGBO_SUPPLIERS},
		as_dict=True,
	)

	plan = {"discount": [], "payment": [], "fix": [], "skipped": []}
	for r in gl_rows:
		kind, bill_no = _classify_remarks(r["remarks"])
		if kind in ("discount", "payment"):
			# 同票号可能存在多条 BoE (期初拆分导致), 全部取出按面值拆分迁移单据
			boes = frappe.db.sql(
				"""
				SELECT name, bill_amount, due_date
				FROM `tabBill of Exchange`
				WHERE bill_no=%s
				ORDER BY name
				""",
				(bill_no,),
				as_dict=True,
			)
			if not boes:
				plan["skipped"].append({"je": r["je_name"], "reason": f"BoE not found for {bill_no}", "remarks": r["remarks"]})
				continue
			total_face = sum(float(b["bill_amount"] or 0) for b in boes)
			received = float(r["credit"] or 0)  # Cr 金额 = 银行实收
			entry = {
				"je": r["je_name"],
				"gl": r["gl_name"],
				"date": str(r["posting_date"]),
				"bill_no": bill_no,
				"boes": [{"name": b["name"], "face": float(b["bill_amount"] or 0), "due_date": str(b["due_date"]) if b["due_date"] else None} for b in boes],
				"total_face": total_face,
				"received": received,
				"cheque_no": r["cheque_no"],
				"user_remark": r["user_remark"],
			}
			plan[kind].append(entry)
		elif kind == "fix":
			plan["fix"].append({
				"je": r["je_name"],
				"gl": r["gl_name"],
				"date": str(r["posting_date"]),
				"amount": float(r["credit"] or 0),
				"cheque_no": r["cheque_no"],
				"user_remark": r["user_remark"],
			})
		else:
			plan["skipped"].append({"je": r["je_name"], "reason": "unclassified", "remarks": r["remarks"]})

	if dry_run:
		return {
			"dry_run": True,
			"discount_count": len(plan["discount"]),
			"payment_count": len(plan["payment"]),
			"fix_count": len(plan["fix"]),
			"skipped_count": len(plan["skipped"]),
			"plan": plan,
		}

	# ---------------- 真正执行 ----------------
	result = {"discount": [], "payment": [], "fix": [], "skipped": plan["skipped"]}

	# 2. 处理贴现 — 删老 JE, 按面值拆分新建 Bill Discount(s)
	for e in plan["discount"]:
		total_face = e["total_face"]
		received = e["received"]
		total_interest = round(total_face - received, 2)
		if total_interest < 0:
			result["skipped"].append({"je": e["je"], "reason": f"interest negative: face={total_face}, received={received}"})
			continue

		# 按面值比例分摊实收与利息, 最后一条吸收分位舍入差
		allocs = _allocate_proportional(e["boes"], received, total_interest)

		_delete_je_completely(e["je"])

		bd_names = []
		for boe, alloc_actual, alloc_interest in allocs:
			face = boe["face"]
			remaining = max(date_diff(boe["due_date"], getdate(e["date"])), 1) if boe["due_date"] else 1
			bd = frappe.new_doc("Bill Discount")
			bd.flags.historical_import = True
			bd.bill_of_exchange = boe["name"]
			bd.company = _COMPANY
			bd.posting_date = e["date"]
			bd.discount_bank = "宁波银行"
			bd.discount_date = e["date"]
			bd.remaining_days = remaining
			bd.discount_rate = round(alloc_interest / (face * remaining / 360) * 100, 6) if face else 0
			bd.discount_amount = face
			bd.discount_interest = alloc_interest
			bd.actual_amount = alloc_actual
			bd.bank_account = _BANK_ACCOUNT
			bd.notes_receivable_account = _NR_ACCOUNT
			bd.interest_account = _INTEREST_ACCOUNT
			bd.insert(ignore_permissions=True)
			bd.submit()
			bd_names.append({"bill_discount": bd.name, "boe": boe["name"], "face": face, "actual": alloc_actual, "interest": alloc_interest})

		result["discount"].append({
			"old_je": e["je"], "bill_no": e["bill_no"],
			"total_face": total_face, "total_received": received, "total_interest": total_interest,
			"created": bd_names,
		})

	# 3. 处理到期兑付 — 删老 JE, 按面值拆分新建 Bill Payment(s)
	for e in plan["payment"]:
		total_face = e["total_face"]
		received = e["received"]
		if abs(total_face - received) > 0.01:
			result["skipped"].append({"je": e["je"], "reason": f"payment amount mismatch total_face={total_face} received={received}"})
			continue

		# 兑付无贴现利息, 只按面值分到各 BoE (一般也只有 1 条)
		allocs = _allocate_proportional(e["boes"], received, 0.0)

		_delete_je_completely(e["je"])

		bp_names = []
		for boe, alloc_actual, _ in allocs:
			bp = frappe.new_doc("Bill Payment")
			bp.flags.historical_import = True
			bp.bill_of_exchange = boe["name"]
			bp.company = _COMPANY
			bp.payment_date = e["date"]
			bp.posting_date = e["date"]
			bp.payment_amount = boe["face"]
			bp.payment_status = "Paid"
			bp.bank_account = _BANK_ACCOUNT
			bp.notes_receivable_account = _NR_ACCOUNT
			bp.insert(ignore_permissions=True)
			bp.submit()
			bp_names.append({"bill_payment": bp.name, "boe": boe["name"], "amount": boe["face"]})

		result["payment"].append({
			"old_je": e["je"], "bill_no": e["bill_no"],
			"total_face": total_face, "total_received": received,
			"created": bp_names,
		})

	# 4. 处理金额修正 — 保留 JE, 把应付账款-结算 搬到 11215 票据清算中, 清空 party
	fix_je_names = sorted({e["je"] for e in plan["fix"]})
	if fix_je_names:
		placeholders = ",".join(["%s"] * len(fix_je_names))
		frappe.db.sql(
			f"""
			UPDATE `tabGL Entry`
			SET account=%s, party_type=NULL, party=NULL
			WHERE voucher_no IN ({placeholders})
			  AND voucher_type='Journal Entry'
			  AND account=%s
			  AND is_cancelled=0
			""",
			(_CLEARING_ACCOUNT, *fix_je_names, _PAYABLE_SETTLEMENT),
		)
		frappe.db.sql(
			f"""
			UPDATE `tabJournal Entry Account`
			SET account=%s, party_type=NULL, party=NULL, against_account=%s
			WHERE parent IN ({placeholders})
			  AND account=%s
			""",
			(_CLEARING_ACCOUNT, _BANK_ACCOUNT, *fix_je_names, _PAYABLE_SETTLEMENT),
		)
		# PLE 是按 party 展开的, clearing 不是 Receivable/Payable type, 直接删
		frappe.db.sql(
			f"""
			DELETE FROM `tabPayment Ledger Entry`
			WHERE voucher_type='Journal Entry'
			  AND voucher_no IN ({placeholders})
			""",
			tuple(fix_je_names),
		)
		for je in fix_je_names:
			result["fix"].append({"je": je, "moved_to": _CLEARING_ACCOUNT})

	frappe.db.commit()

	# 5. 回检: 确认已不再有宁波银行 party 关联
	remaining_gl = frappe.db.sql(
		"""
		SELECT COUNT(*) FROM `tabGL Entry`
		WHERE party_type='Supplier' AND party IN %(parties)s AND is_cancelled=0
		""",
		{"parties": _NINGBO_SUPPLIERS},
	)[0][0]
	remaining_ple = frappe.db.sql(
		"""
		SELECT COUNT(*) FROM `tabPayment Ledger Entry`
		WHERE party_type='Supplier' AND party IN %(parties)s
		""",
		{"parties": _NINGBO_SUPPLIERS},
	)[0][0]
	result["remaining_gl_refs"] = remaining_gl
	result["remaining_ple_refs"] = remaining_ple
	return result


@frappe.whitelist()
def delete_ningbo_bank_supplier():
	"""彻底删除"宁波银行"与"SUP-2070"两个 Supplier.

	前置条件: migrate_ningbo_bank_supplier(dry_run=0) 已成功跑完且无残留引用.
	若仍有 GL / PLE / PE / PI 等引用, 直接 throw.
	"""
	_require_admin()

	# 硬约束: 不能有活跃 GL/PLE 残留
	gl_cnt = frappe.db.sql(
		"""
		SELECT COUNT(*) FROM `tabGL Entry`
		WHERE party_type='Supplier' AND party IN %(p)s AND is_cancelled=0
		""",
		{"p": _NINGBO_SUPPLIERS},
	)[0][0]
	if gl_cnt:
		frappe.throw(_("Still {0} active GL Entries reference 宁波银行, run migrate first").format(gl_cnt))

	ple_cnt = frappe.db.sql(
		"SELECT COUNT(*) FROM `tabPayment Ledger Entry` WHERE party_type='Supplier' AND party IN %(p)s",
		{"p": _NINGBO_SUPPLIERS},
	)[0][0]
	if ple_cnt:
		frappe.db.sql(
			"DELETE FROM `tabPayment Ledger Entry` WHERE party_type='Supplier' AND party IN %(p)s",
			{"p": _NINGBO_SUPPLIERS},
		)

	# Payment Entry / Purchase Invoice 检查
	for dt, field in (("Payment Entry", "party"), ("Purchase Invoice", "supplier")):
		cnt = frappe.db.sql(
			f"SELECT COUNT(*) FROM `tab{dt}` WHERE `{field}` IN %(p)s AND docstatus<2",
			{"p": _NINGBO_SUPPLIERS},
		)[0][0]
		if cnt:
			frappe.throw(_("Still {0} {1} reference 宁波银行").format(cnt, dt))

	deleted = []
	for sup in _NINGBO_SUPPLIERS:
		if frappe.db.exists("Supplier", sup):
			frappe.db.sql("DELETE FROM `tabSupplier` WHERE name=%s", (sup,))
			frappe.clear_document_cache("Supplier", sup)
			deleted.append(sup)

	frappe.db.commit()
	return {"deleted": deleted, "cleared_ple": ple_cnt}


# ---------------------------------------------------------------------------
# 把存量 Bill Discount / Bill Payment 的"真实银行叶子账户"搬迁到票据清算中
# ---------------------------------------------------------------------------
#
# 背景: 在引入 "贴现/兑付必须走 11215 票据清算中" 规则之前创建的单据(例如
# 今天刚把宁波银行借壳供应商正规化出的 32 Bill Discount + 3 Bill Payment)
# 仍然把 bank_account 写在 10022 京泰宁波 这样的真实银行叶子账户上, 会和
# 未来银行流水导入规则产生不一致.
#
# 本工具扫描所有 docstatus=1 的 Bill Discount/Bill Payment, 找 bank_account
# 指向 account_type='Bank' 的账户的那些, 把:
#   1. 单据本身的 bank_account 字段改为 11215 票据清算中
#   2. 对应 GL Entry 中 account 为该银行叶子 的条目改为 11215 票据清算中
#   3. 被改动的 GL 条目上的 against_account 也同步刷新
#
# 注意: 这个工具只搬"acceptance 侧"产生的 GL, 不碰任何银行流水 JE. 跑完之后
# 原来那些真实银行账户上的"贴现/兑付入账"会消失, 需要靠银行流水导入时重新把
# 银行侧的到账条目生成出来(通常历史银行流水已经有了, 不需要额外动作).
# 幂等: 第二次跑返回 moved=0.
# ---------------------------------------------------------------------------


@frappe.whitelist()
def normalize_bill_settlement_to_clearing(dry_run=1):
	"""把存量 Bill Discount / Bill Payment 从真实银行叶子账户搬到清算中.

	参数:
		dry_run: 默认 1 只打印计划, 传 0 才真改.
	"""
	_require_admin()
	if isinstance(dry_run, str):
		dry_run = dry_run.lower() not in ("0", "false", "no", "")

	# 1. 找出 account_type='Bank' 的叶子账户清单
	bank_accounts = [
		r[0]
		for r in frappe.db.sql(
			"SELECT name FROM `tabAccount` WHERE account_type='Bank' AND is_group=0"
		)
	]
	if not bank_accounts:
		return {"dry_run": dry_run, "moved_docs": 0, "moved_gl": 0, "note": "no bank leaf accounts found"}

	# 2. 找所有 bank_account 落在银行叶子上的已提交 Bill Discount / Bill Payment
	plan = {"Bill Discount": [], "Bill Payment": []}
	for dt in ("Bill Discount", "Bill Payment"):
		rows = frappe.db.sql(
			f"""
			SELECT name, bank_account
			FROM `tab{dt}`
			WHERE docstatus=1 AND bank_account IN %(banks)s
			ORDER BY name
			""",
			{"banks": tuple(bank_accounts)},
			as_dict=True,
		)
		plan[dt] = rows

	total_docs = sum(len(v) for v in plan.values())

	if dry_run:
		return {
			"dry_run": True,
			"bank_accounts_in_scope": bank_accounts,
			"clearing_target": _CLEARING_ACCOUNT,
			"Bill Discount_count": len(plan["Bill Discount"]),
			"Bill Payment_count": len(plan["Bill Payment"]),
			"total_docs": total_docs,
			"sample": {
				"Bill Discount": plan["Bill Discount"][:5],
				"Bill Payment": plan["Bill Payment"][:5],
			},
		}

	# ---------------- 真正执行 ----------------
	moved_gl = 0
	moved_docs_detail = {"Bill Discount": [], "Bill Payment": []}

	for dt, rows in plan.items():
		for r in rows:
			doc_name = r["name"]
			old_bank = r["bank_account"]

			# 2a. 单据字段
			frappe.db.sql(
				f"UPDATE `tab{dt}` SET bank_account=%s WHERE name=%s",
				(_CLEARING_ACCOUNT, doc_name),
			)

			# 2b. GL Entry account 字段 (Dr 银行侧 → Dr 清算中)
			frappe.db.sql(
				"""
				UPDATE `tabGL Entry`
				SET account=%s
				WHERE voucher_type=%s
				  AND voucher_no=%s
				  AND account=%s
				  AND is_cancelled=0
				""",
				(_CLEARING_ACCOUNT, dt, doc_name, old_bank),
			)
			rc = frappe.db.sql("SELECT ROW_COUNT()")[0][0]
			moved_gl += rc

			# 2c. against_account: 原来 against 是银行的条目(也就是 Cr 应收票据侧)
			#     现在 against 改成清算中, 让 GL 双向可读
			frappe.db.sql(
				"""
				UPDATE `tabGL Entry`
				SET against=REPLACE(against, %s, %s)
				WHERE voucher_type=%s
				  AND voucher_no=%s
				  AND is_cancelled=0
				  AND against LIKE CONCAT('%%', %s, '%%')
				""",
				(old_bank, _CLEARING_ACCOUNT, dt, doc_name, old_bank),
			)

			frappe.clear_document_cache(dt, doc_name)
			moved_docs_detail[dt].append({"name": doc_name, "from": old_bank, "to": _CLEARING_ACCOUNT})

	frappe.db.commit()

	# 3. 复查: 应该无残留
	remaining = frappe.db.sql(
		"""
		SELECT COUNT(*) FROM `tabGL Entry`
		WHERE voucher_type IN ('Bill Discount', 'Bill Payment')
		  AND account IN %(banks)s
		  AND is_cancelled=0
		""",
		{"banks": tuple(bank_accounts)},
	)[0][0]

	return {
		"dry_run": False,
		"moved_docs": total_docs,
		"moved_gl_rows": moved_gl,
		"remaining_on_bank_leaf": remaining,
		"detail": moved_docs_detail,
	}


# ---------------------------------------------------------------------------
# 为历史迁移出来的 Bill Discount/Payment 补一条配对的银行流水 JE
# ---------------------------------------------------------------------------
#
# 背景:
#   migrate_ningbo_bank_supplier 用 _delete_je_completely 把原始的"借壳供应商"
#   JE 整个删掉, 包括银行侧的 Dr 10022 京泰宁波 行. 随后创建 Bill Discount 时,
#   controller 内部又会生成一条 Dr 10022 凭空"补"出银行入账. 再之后跑
#   normalize_bill_settlement_to_clearing 把这条 Dr 从 10022 搬到 11215 清算中,
#   结果: 10022 京泰宁波账户上那 3.72M 实际收到的承兑资金凭空消失了, 与宁波
#   银行真实对账单不一致.
#
#   正确做法: 独立创建一条银行流水镜像 JE, Dr 10022 / Cr 11215, 金额 = 单据
#   在 11215 上的 Dr (即贴现实收 / 兑付面值). 补完后 10022 余额回正, 11215
#   清算中借贷自然对冲.
#
#   本函数以 cheque_no='MIRROR-<doc_name>' 做幂等标记, 重复跑不会创建重复 JE.
# ---------------------------------------------------------------------------


@frappe.whitelist()
def purge_empty_mirror_journal_entries():
	"""清掉上一轮 bug 版本创建的零金额 MIRROR JE (没有 GL, 直接 SQL 删).

	仅清理 cheque_no LIKE 'MIRROR-%' AND total_debit=0 AND docstatus=1 的 JE.
	幂等.
	"""
	_require_admin()
	rows = frappe.db.sql(
		"""
		SELECT name FROM `tabJournal Entry`
		WHERE cheque_no LIKE 'MIRROR-%%'
		  AND total_debit=0
		  AND docstatus=1
		"""
	)
	names = [r[0] for r in rows]
	if not names:
		return {"purged": 0}
	placeholders = ",".join(["%s"] * len(names))
	frappe.db.sql(
		f"DELETE FROM `tabJournal Entry Account` WHERE parent IN ({placeholders})",
		tuple(names),
	)
	frappe.db.sql(
		f"DELETE FROM `tabJournal Entry` WHERE name IN ({placeholders})",
		tuple(names),
	)
	# 以防万一有残影 GL/PLE (这批肯定没有, 但防御一下)
	frappe.db.sql(
		f"DELETE FROM `tabGL Entry` WHERE voucher_type='Journal Entry' AND voucher_no IN ({placeholders})",
		tuple(names),
	)
	frappe.db.sql(
		f"DELETE FROM `tabPayment Ledger Entry` WHERE voucher_type='Journal Entry' AND voucher_no IN ({placeholders})",
		tuple(names),
	)
	frappe.db.commit()
	return {"purged": len(names), "names": names}


@frappe.whitelist()
def create_bank_mirror_for_migrated_bills(
	dry_run=1,
	bank_account="10022 - 京泰宁波 - 台州京泰",
	target_doc_names_json=None,
):
	"""为指定的 Bill Discount/Payment 单据补一条配对的银行流水 JE.

	参数:
		dry_run: 默认 1 只打印计划.
		bank_account: 镜像 JE 的 Dr 侧账户, 默认 10022 京泰宁波 (宁波银行迁移场景).
		target_doc_names_json: JSON 数组, 指定单据列表. 默认 None 时自动选取
			"今天迁移的 37 张" — 具体识别逻辑: 所有 docstatus=1 的 Bill Discount/
			Payment 中, 其 11215 Dr 的 GL Entry 尚未有对应的 JE Cr 11215
			配对 (按 voucher_no='MIRROR-<name>' 检查).
	"""
	_require_admin()
	if isinstance(dry_run, str):
		dry_run = dry_run.lower() not in ("0", "false", "no", "")

	# 校验账户
	acc = frappe.db.get_value("Account", bank_account, ["is_group", "account_type"], as_dict=True)
	if not acc:
		frappe.throw(f"Bank account {bank_account} not found")
	if acc.is_group:
		frappe.throw(f"{bank_account} is a group account")

	# 1. 筛选目标单据
	if target_doc_names_json:
		names = frappe.parse_json(target_doc_names_json) if isinstance(target_doc_names_json, str) else target_doc_names_json
	else:
		# 默认: 所有已经把 bank_account 搬到 11215 清算中但还没有 MIRROR JE 的 BD/BP
		names = []
		for dt in ("Bill Discount", "Bill Payment"):
			rows = frappe.db.sql(
				f"""
				SELECT d.name
				FROM `tab{dt}` d
				WHERE d.docstatus=1
				  AND d.bank_account=%s
				  AND NOT EXISTS (
					SELECT 1 FROM `tabJournal Entry` je
					WHERE je.cheque_no = CONCAT('MIRROR-', d.name)
					  AND je.docstatus=1
				  )
				""",
				(_CLEARING_ACCOUNT,),
			)
			names.extend([(dt, r[0]) for r in rows])
	# 格式化为 (dt, name) 元组
	if names and isinstance(names[0], str):
		# 用户只传了名字, 按前缀猜 doctype
		names = [("Bill Discount" if n.startswith("DISC-") else "Bill Payment", n) for n in names]

	# 2. 对每张单据: 读 11215 Dr 金额 + 日期, 组装镜像 JE
	plan = []
	for dt, doc_name in names:
		gl = frappe.db.sql(
			"""
			SELECT posting_date, debit, remarks
			FROM `tabGL Entry`
			WHERE voucher_type=%s AND voucher_no=%s
			  AND account=%s
			  AND is_cancelled=0
			LIMIT 1
			""",
			(dt, doc_name, _CLEARING_ACCOUNT),
			as_dict=True,
		)
		if not gl:
			continue
		amount = float(gl[0]["debit"] or 0)
		if amount <= 0:
			continue
		plan.append({
			"doctype": dt,
			"doc_name": doc_name,
			"date": str(gl[0]["posting_date"]),
			"amount": round(amount, 2),
			"remarks_hint": (gl[0]["remarks"] or "")[:80],
		})

	if dry_run:
		total = sum(p["amount"] for p in plan)
		return {
			"dry_run": True,
			"bank_account": bank_account,
			"clearing_account": _CLEARING_ACCOUNT,
			"target_count": len(plan),
			"total_amount": round(total, 2),
			"sample": plan[:5],
			"plan": plan,
		}

	# ---------------- 真正执行 ----------------
	created = []
	skipped = []
	cost_center = frappe.db.get_value("Company", _COMPANY, "cost_center")

	for p in plan:
		mirror_cheque = f"MIRROR-{p['doc_name']}"

		# 幂等: 如果同 cheque_no 的已提交 JE 已存在则跳过
		if frappe.db.exists("Journal Entry", {"cheque_no": mirror_cheque, "docstatus": 1}):
			skipped.append({"doc": p['doc_name'], "reason": "mirror already exists"})
			continue

		je = frappe.new_doc("Journal Entry")
		je.voucher_type = "Journal Entry"
		je.posting_date = p["date"]
		je.company = _COMPANY
		je.cheque_no = mirror_cheque
		je.cheque_date = p["date"]
		je.user_remark = (
			f"历史补建银行流水镜像: 对应 {p['doctype']} {p['doc_name']}. "
			f"老系统借壳供应商模式下原始 JE 已被删除, 此 JE 补回 10022 的"
			f"到账记录并同时冲减 11215 清算中"
		)
		# 同时填充 debit_in_account_currency 和 debit (否则如果 validate 被跳过,
		# 币种转换就不会发生, JE 会以零金额提交, GL 生成被跳过).
		je.append(
			"accounts",
			{
				"account": bank_account,
				"debit_in_account_currency": p["amount"],
				"debit": p["amount"],
				"credit_in_account_currency": 0,
				"credit": 0,
				"exchange_rate": 1,
				"account_currency": "CNY",
				"cost_center": cost_center,
			},
		)
		je.append(
			"accounts",
			{
				"account": _CLEARING_ACCOUNT,
				"debit_in_account_currency": 0,
				"debit": 0,
				"credit_in_account_currency": p["amount"],
				"credit": p["amount"],
				"exchange_rate": 1,
				"account_currency": "CNY",
				"cost_center": cost_center,
			},
		)
		je.total_debit = p["amount"]
		je.total_credit = p["amount"]
		# 允许历史财年日期
		je.flags.ignore_permissions = True
		try:
			je.insert(ignore_permissions=True)
			je.submit()
		except Exception as e:
			skipped.append({"doc": p['doc_name'], "reason": f"create/submit failed: {str(e)[:200]}"})
			continue

		created.append({
			"doc": p['doc_name'],
			"je": je.name,
			"date": p["date"],
			"amount": p["amount"],
		})

	frappe.db.commit()

	# 3. 验证 11215 余额变动
	new_net = frappe.db.sql(
		"SELECT SUM(debit - credit) FROM `tabGL Entry` WHERE account=%s AND is_cancelled=0",
		(_CLEARING_ACCOUNT,),
	)[0][0]
	new_bank_net = frappe.db.sql(
		"SELECT SUM(debit - credit) FROM `tabGL Entry` WHERE account=%s AND is_cancelled=0",
		(bank_account,),
	)[0][0]

	return {
		"dry_run": False,
		"created_count": len(created),
		"skipped_count": len(skipped),
		"total_amount_mirrored": round(sum(c["amount"] for c in created), 2),
		"clearing_net_after": float(new_net or 0),
		"bank_net_after": float(new_bank_net or 0),
		"created": created,
		"skipped": skipped,
	}
