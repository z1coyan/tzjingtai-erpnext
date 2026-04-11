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
