import re

import frappe
from frappe import _
from frappe.model.naming import getseries


AUTO_SEQUENCE_MODE = "Auto Sequence"
MANUAL_WITH_PREFIX_MODE = "Manual With Prefix"
AUTO_CODE_PATTERN = re.compile(r"^(?P<prefix>[A-Z](?:\([A-Z]+\))?)-(?P<number>\d+)$")


def extract_item_group_code(item_group: str | None) -> str | None:
    if not item_group:
        return None

    code = item_group.split(":", 1)[0].strip()
    if not code or code == item_group:
        return None

    return code


@frappe.whitelist()
def get_item_code_context(item_group: str | None) -> dict[str, str]:
    config = _get_item_code_config(item_group)
    context = {
        "prefix": config["prefix"],
        "mode": config["mode"],
    }

    if config["mode"] == AUTO_SEQUENCE_MODE:
        context["preview"] = _peek_next_item_code(config["prefix"])
    else:
        context["preview"] = config["prefix"]

    return context


def before_naming_item(doc, method=None):
    config = _get_item_code_config(doc.item_group)
    if config["mode"] != AUTO_SEQUENCE_MODE:
        return

    doc.item_code = _allocate_next_item_code(config["prefix"])


def validate_item(doc, method=None):
    config = _get_item_code_config(doc.item_group)
    if config["mode"] != MANUAL_WITH_PREFIX_MODE:
        return

    prefix = config["prefix"]
    item_code = (doc.item_code or "").strip()
    suffix = item_code[len(prefix) :].strip() if item_code.startswith(prefix) else ""
    if suffix:
        doc.item_code = f"{prefix}{suffix}"
        _validate_item_code_not_exists(doc)
        return

    example = f"{prefix}19-1" if prefix == "F(P)" else f"{prefix}X"
    frappe.throw(
        _("Item code must start with {0} and include the custom suffix, for example {1}.").format(
            prefix, example
        )
    )


def _get_item_code_config(item_group: str | None) -> dict[str, str]:
    if not item_group:
        frappe.throw(_("Select an Item Group before loading item code settings."))

    item_group_doc = frappe.db.get_value(
        "Item Group",
        item_group,
        ["is_group", "custom_item_code_prefix", "custom_item_code_mode"],
        as_dict=True,
    )
    if not item_group_doc:
        frappe.throw(_("Item Group {0} does not exist.").format(item_group))

    if item_group_doc.is_group:
        frappe.throw(_("Item Group {0} is a group and cannot be used directly for items.").format(item_group))

    prefix = _normalize_prefix(item_group_doc.custom_item_code_prefix) or extract_item_group_code(item_group)
    if not prefix:
        frappe.throw(_("Item Group {0} has no item code prefix configured.").format(item_group))

    mode = (item_group_doc.custom_item_code_mode or _infer_item_code_mode(prefix) or "").strip()
    if not mode:
        frappe.throw(_("Item Group {0} has no item code mode configured.").format(item_group))

    return {
        "prefix": prefix,
        "mode": mode,
    }


def _infer_item_code_mode(prefix: str | None) -> str | None:
    if not prefix:
        return None

    if prefix == "F(P)":
        return MANUAL_WITH_PREFIX_MODE

    return AUTO_SEQUENCE_MODE


def _normalize_prefix(prefix: str | None) -> str | None:
    if not prefix:
        return None

    normalized = prefix.strip()
    if normalized.endswith("-"):
        normalized = normalized[:-1].strip()

    return normalized or None


def _allocate_next_item_code(prefix: str) -> str:
    series_key = _get_series_key(prefix)
    _ensure_series_floor(series_key, prefix)

    for _ in range(3):
        candidate = f"{series_key}{getseries(series_key, 1)}"
        if not _item_code_exists(candidate):
            return candidate
        _ensure_series_floor(series_key, prefix)

    frappe.throw(
        _("Unable to allocate a unique item code for prefix {0}. Please retry.").format(prefix)
    )


def _peek_next_item_code(prefix: str) -> str:
    series_key = _get_series_key(prefix)
    current = max(_get_series_current(series_key), _find_max_existing_sequence(prefix))

    return f"{series_key}{int(current or 0) + 1}"


def _get_series_key(prefix: str) -> str:
    return f"{prefix}-"


def _get_series_current(series_key: str) -> int:
    result = frappe.db.sql(
        """
        SELECT `current`
        FROM `tabSeries`
        WHERE `name` = %s
        """,
        (series_key,),
    )
    if not result:
        return 0

    return int(result[0][0] or 0)


def _ensure_series_floor(series_key: str, prefix: str):
    max_number = _find_max_existing_sequence(prefix)
    if max_number <= 0:
        return

    # 首次切到官方序列，或历史上有人手工插入了更大的编码时，
    # 把 Series 至少推进到当前已存在的最大流水号。
    frappe.db.sql(
        """
        INSERT INTO `tabSeries` (`name`, `current`)
        VALUES (%s, %s)
        ON DUPLICATE KEY UPDATE `current` = GREATEST(`current`, VALUES(`current`))
        """,
        (series_key, max_number),
    )


def _validate_item_code_not_exists(doc):
    existing_name = frappe.db.get_value("Item", {"item_code": doc.item_code}, "name")
    if existing_name and existing_name != doc.name:
        frappe.throw(_("Item code {0} already exists.").format(doc.item_code))


def _item_code_exists(item_code: str) -> bool:
    return bool(frappe.db.exists("Item", item_code))


def _find_max_existing_sequence(prefix: str) -> int:
    item_codes = frappe.get_all(
        "Item",
        filters={"item_code": ["like", f"{prefix}-%"]},
        pluck="item_code",
        limit_page_length=100000,
    )

    max_number = 0
    for item_code in item_codes:
        match = AUTO_CODE_PATTERN.match(item_code or "")
        if match and match.group("prefix") == prefix:
            max_number = max(max_number, int(match.group("number")))

    return max_number
