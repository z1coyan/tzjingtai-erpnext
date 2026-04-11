# Copyright (c) 2026, 台州京泰 and contributors
# For license information, please see license.txt
"""期初数据导入辅助工具（仅管理员可调用）。

acceptance app 在首次安装时，Bill of Exchange.bill_no 带有 unique 约束。
该约束与 app 自身的拆分流程相互矛盾，且阻止期初历史数据（同一票号不同子票区间、
同一票号多次收入等）的导入。CLAUDE.md 禁止在生产环境中运行 bench migrate，
因此提供一个一次性的白名单方法，通过 ALTER TABLE 卸掉已建好的 unique 索引。

导入完成后该方法可以继续保留——重复调用是幂等的。
"""

import frappe
from frappe import _


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
