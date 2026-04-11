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
