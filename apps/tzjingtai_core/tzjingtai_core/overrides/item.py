# 物料编码自动生成
#
# 业务规则：
#   - item_group = "F(P) 客户产品"：由用户手填，必须以 F(P) 开头
#   - 其它叶子分组（F(BG)、F(BXGJ)、E(L)、M(S)、P(FC) 等）：自动生成 <prefix>-<N>
#     其中 prefix 从 item_group 名字里抠括号段，N = 该 prefix 现有最大序号 + 1
#
# 之所以不用 ERPNext 的 Naming Series：
#   1. Stock Settings.item_naming_by 是全局单选，无法按 item_group 分流
#   2. make_autoname 基于 tabSeries 独立计数，历史数据不是用它生成的，直接用会撞号
# 因此采用 before_insert 钩子，查当前最大尾号 + 1，简单可控。

import re

import frappe
from frappe import _

# F(P) 组需要用户手填，其它组自动生成
CUSTOMER_PRODUCT_GROUP = "F(P) 客户产品"
CUSTOMER_PRODUCT_PREFIX = "F(P)"

# 从 item_group 名抠出括号前缀，例如 "F(BG) 金属棒/管" -> "F(BG)"
_GROUP_PREFIX_RE = re.compile(r"^([A-Z]+\([A-Z]+\))")

# 料号是否为用户未填写时 Desk 自动塞的占位符
_PLACEHOLDER_PREFIXES = ("new-item", "New Item")


def set_item_code_by_group(doc, method=None):
	"""Item.before_insert 钩子：按分组规则生成或校验 item_code。"""
	item_group = (doc.item_group or "").strip()
	if not item_group:
		return  # 交给 ERPNext 原生校验报错

	if item_group == CUSTOMER_PRODUCT_GROUP:
		_validate_customer_product_code(doc)
	else:
		_auto_generate_code(doc, item_group)

	# Stock Settings.item_naming_by = "Item Code" 时，name 跟随 item_code
	doc.name = doc.item_code


def _is_placeholder(code: str) -> bool:
	if not code:
		return True
	return code.startswith(_PLACEHOLDER_PREFIXES)


def _validate_customer_product_code(doc):
	if _is_placeholder(doc.item_code):
		frappe.throw(
			_("Customer product items must have a manually entered Item Code starting with {0}").format(
				CUSTOMER_PRODUCT_PREFIX
			)
		)
	if not doc.item_code.startswith(CUSTOMER_PRODUCT_PREFIX):
		frappe.throw(
			_("Customer product Item Code must start with {0}").format(CUSTOMER_PRODUCT_PREFIX)
		)


def _auto_generate_code(doc, item_group: str):
	# 用户已手填且不是占位符，尊重用户输入，不覆盖
	if not _is_placeholder(doc.item_code):
		return

	match = _GROUP_PREFIX_RE.match(item_group)
	if not match:
		# 不符合 "X(Y) xxx" 命名规范的分组，交给用户手填，不自动生成
		frappe.throw(
			_("Item Group {0} has no standard prefix; please enter Item Code manually").format(
				item_group
			)
		)

	prefix = match.group(1)
	doc.item_code = _next_code_for_prefix(prefix)


def _next_code_for_prefix(prefix: str) -> str:
	"""查该 prefix 下现存 item_code 的最大尾号 + 1。"""
	like = f"{prefix}-%"
	# 用 REGEXP 只取严格符合 "<prefix>-<digits>" 的行，避免 F(P)1-1 这类客户自定义编码干扰
	pattern = f"^{re.escape(prefix)}-[0-9]+$"
	rows = frappe.db.sql(
		"""
		SELECT item_code FROM `tabItem`
		WHERE item_code LIKE %s AND item_code REGEXP %s
		""",
		(like, pattern),
	)
	max_n = 0
	tail_re = re.compile(r"-(\d+)$")
	for (code,) in rows:
		m = tail_re.search(code)
		if m:
			n = int(m.group(1))
			if n > max_n:
				max_n = n
	return f"{prefix}-{max_n + 1}"
