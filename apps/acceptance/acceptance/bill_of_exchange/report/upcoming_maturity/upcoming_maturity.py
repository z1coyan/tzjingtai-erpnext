"""Upcoming Maturity —— 未到期 / 即将到期的承兑汇票。"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import add_days, today


def execute(filters=None):
    filters = filters or {}
    days = int(filters.get("days") or _default_alert_days())
    columns = _columns()
    data = _get_data(days)
    return columns, data


def _default_alert_days() -> int:
    try:
        return int(
            frappe.db.get_single_value("Bill of Exchange Settings", "maturity_alert_days") or 15
        )
    except Exception:
        return 15


def _columns():
    return [
        {"label": _("Bill No"), "fieldname": "name", "fieldtype": "Link", "options": "Bill of Exchange", "width": 160},
        {"label": _("Bill Type"), "fieldname": "bill_type", "fieldtype": "Data", "width": 160},
        {"label": _("Drawer"), "fieldname": "drawer_name", "fieldtype": "Data", "width": 180},
        {"label": _("Drawee Bank"), "fieldname": "drawee_bank", "fieldtype": "Data", "width": 180},
        {"label": _("Maturity Date"), "fieldname": "maturity_date", "fieldtype": "Date", "width": 120},
        {"label": _("Days Left"), "fieldname": "days_left", "fieldtype": "Int", "width": 100},
        {"label": _("Face Amount"), "fieldname": "face_amount", "fieldtype": "Currency", "width": 140},
        {"label": _("Outstanding Amount"), "fieldname": "outstanding_amount", "fieldtype": "Currency", "width": 160},
        {"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 140},
    ]


def _get_data(days: int):
    limit_date = add_days(today(), days)
    rows = frappe.db.sql(
        """
        SELECT
            name, bill_type, drawer_name, drawee_bank,
            maturity_date, face_amount, outstanding_amount, status,
            DATEDIFF(maturity_date, CURDATE()) AS days_left
        FROM `tabBill of Exchange`
        WHERE status IN ('Active', 'Partially Settled')
          AND maturity_date IS NOT NULL
          AND maturity_date <= %s
        ORDER BY maturity_date ASC
        """,
        (limit_date,),
        as_dict=True,
    )
    return rows
