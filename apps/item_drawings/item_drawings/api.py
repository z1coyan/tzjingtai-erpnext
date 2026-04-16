import json

import frappe
from frappe import _


@frappe.whitelist()
def get_item_drawing_status(item_codes: str | list[str] | None = None) -> dict[str, dict[str, int | bool]]:
    codes = _normalize_item_codes(item_codes)
    if not codes:
        return {}

    rows = frappe.get_all(
        "Item Drawing",
        filters={
            "parent": ["in", codes],
            "parenttype": "Item",
            "parentfield": "custom_drawings",
            "disabled": 0,
            "drawing_file": ["!=", ""],
        },
        fields=["parent"],
        limit_page_length=100000,
    )

    active_counts = {code: 0 for code in codes}
    for row in rows:
        active_counts[row.parent] = active_counts.get(row.parent, 0) + 1

    return {
        code: {
            "has_active_drawings": active_counts.get(code, 0) > 0,
            "active_count": active_counts.get(code, 0),
        }
        for code in codes
    }


def normalize_item_drawings(doc, method=None):
    rows = list(doc.get("custom_drawings") or [])
    if not rows:
        return

    active_rows = [row for row in rows if row.drawing_file and not row.disabled]
    if not active_rows:
        for row in rows:
            row.is_main = 0
        return

    main_row = next((row for row in active_rows if row.is_main), None)
    if not main_row:
        main_row = active_rows[0]

    for row in rows:
        row.is_main = 1 if row.name == main_row.name else 0


def _normalize_item_codes(item_codes):
    if item_codes is None:
        return []

    if isinstance(item_codes, str):
        try:
            item_codes = json.loads(item_codes)
        except json.JSONDecodeError:
            item_codes = [item_codes]

    if not isinstance(item_codes, list):
        frappe.throw(_("Item codes must be a list."))

    normalized = []
    seen = set()
    for code in item_codes:
        code = (code or "").strip()
        if not code or code in seen:
            continue
        seen.add(code)
        normalized.append(code)

    return normalized
