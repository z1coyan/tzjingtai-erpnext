# 物料编码自动生成
#
# 业务规则：
#   - item_group = "F(P) 客户产品"：由用户手填，必须以 F(P) 开头
#   - 其它叶子分组（F(BG)、F(BXGJ)、E(L)、M(S)、P(FC) 等）：自动生成 <prefix>-<N>
#     其中 prefix 从 item_group 名字里抠括号段，N 由 Frappe 原生 tabSeries 计数器递增
#
# 编号机制（懒 seed + 原子递增）：
#   - 复用 Frappe 的 `tabSeries` 表和 `getseries` 底层 primitive，每个前缀对应一行
#     计数器（key = "F(BG)-"），递增走 "SELECT ... FOR UPDATE" + "UPDATE current + 1"，
#     依赖 InnoDB 行锁保证并发下不撞号。这是 ERPNext 所有 naming series 背后的机制。
#   - 首次用到某个前缀时，因为 tabSeries.current 初始为 0 会跟历史数据撞车，需要先扫
#     一次 tabItem 把 current 初始化为历史 max —— 此即 _ensure_series_seeded。seed 只
#     在每个前缀生命周期内跑一次，之后每次新建只是 O(1) 的行锁递增。
#   - 不用 make_autoname("prefix-.#####") 因为 # 个数固定了补零宽度，历史数据是变宽
#     格式（F(BG)-1 到 F(BG)-50），改定宽会风格断裂；因此直接调 getseries(key, 0)，
#     digits=0 时返回不补零的纯十进制串。
#
# 为什么不用 ERPNext Item 的 Naming Series 字段：
#   1. Stock Settings.item_naming_by 是全局单选，无法按 item_group 分流
#   2. 即使开了 Naming Series，模板是 Item DocType 级别的单一模板，同样无法分组切换

import re

import frappe
from frappe import _
from frappe.model.naming import getseries

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
	"""从 Frappe 原生 tabSeries 取下一个序号，首次使用时自动用历史 max 初始化。"""
	key = f"{prefix}-"
	_ensure_series_seeded(prefix, key)
	# digits=0 → 不补零，保持与历史数据 "F(BG)-50" 的变宽风格一致
	num = getseries(key, 0)
	return f"{prefix}-{num}"


def _ensure_series_seeded(prefix: str, key: str) -> None:
	"""懒初始化 tabSeries：首次遇到该前缀时，把 current 对齐到历史数据 max。

	已 seed 过的前缀直接跳过，不再扫描 tabItem —— 这是本函数与"每次查 max"方案的
	根本区别：tabItem 扫描只发生一次，之后每次新建 Item 是 O(1) 的行锁递增。
	"""
	if frappe.db.sql("SELECT 1 FROM `tabSeries` WHERE name=%s", key):
		return

	max_n = _find_max_existing_n(prefix)
	# 并发下两个请求同时 seed：ON DUPLICATE KEY UPDATE 取较大者，保证不回退
	frappe.db.sql(
		"""
		INSERT INTO `tabSeries` (name, `current`) VALUES (%s, %s)
		ON DUPLICATE KEY UPDATE `current` = GREATEST(`current`, VALUES(`current`))
		""",
		(key, max_n),
	)


def _find_max_existing_n(prefix: str) -> int:
	"""扫描 tabItem 找该 prefix 下"<prefix>-<纯数字>"格式的最大尾号。

	仅在首次 seed 时调用一次。REGEXP 过滤掉 F(P)1-1、F(BG)-ABC 这类非规范编码，
	确保自动序号只跟"规范编码"较劲，不被客户自定义编码污染。
	"""
	pattern = f"^{re.escape(prefix)}-[0-9]+$"
	rows = frappe.db.sql(
		"""
		SELECT item_code FROM `tabItem`
		WHERE item_code LIKE %s AND item_code REGEXP %s
		""",
		(f"{prefix}-%", pattern),
	)
	max_n = 0
	tail_re = re.compile(r"-(\d+)$")
	for (code,) in rows:
		m = tail_re.search(code)
		if m:
			n = int(m.group(1))
			if n > max_n:
				max_n = n
	return max_n
