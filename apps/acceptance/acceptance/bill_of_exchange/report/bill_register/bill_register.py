"""Bill Register —— 所有子票段 × 当前状态 + 持有人 + 到期日。"""

from __future__ import annotations

import frappe
from frappe import _


def execute(filters=None):
    filters = filters or {}
    columns = _columns()
    data = _get_data(filters)
    return columns, data


def _columns():
    return [
        {"label": _("Bill No"), "fieldname": "bill_no", "fieldtype": "Link", "options": "Bill of Exchange", "width": 150},
        {"label": _("Bill Type"), "fieldname": "bill_type", "fieldtype": "Data", "width": 150},
        {"label": _("Segment No"), "fieldname": "segment_no", "fieldtype": "Data", "width": 120},
        {"label": _("From"), "fieldname": "segment_from", "fieldtype": "Data", "width": 100},
        {"label": _("To"), "fieldname": "segment_to", "fieldtype": "Data", "width": 100},
        {"label": _("Amount"), "fieldname": "amount", "fieldtype": "Currency", "width": 120},
        {"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 120},
        {"label": _("Holder"), "fieldname": "holder", "fieldtype": "Dynamic Link", "options": "holder_type", "width": 160},
        {"label": _("Holder Type"), "fieldname": "holder_type", "fieldtype": "Data", "width": 100},
        {"label": _("Maturity Date"), "fieldname": "maturity_date", "fieldtype": "Date", "width": 120},
        {"label": _("Drawer"), "fieldname": "drawer_name", "fieldtype": "Data", "width": 180},
        {"label": _("Drawee Bank"), "fieldname": "drawee_bank", "fieldtype": "Data", "width": 180},
    ]


def _get_data(filters):
    conditions = ["1 = 1"]
    values = {}
    if filters.get("bill_type"):
        conditions.append("boe.bill_type = %(bill_type)s")
        values["bill_type"] = filters["bill_type"]
    if filters.get("segment_status"):
        conditions.append("seg.status = %(segment_status)s")
        values["segment_status"] = filters["segment_status"]
    if filters.get("from_date"):
        conditions.append("boe.maturity_date >= %(from_date)s")
        values["from_date"] = filters["from_date"]
    if filters.get("to_date"):
        conditions.append("boe.maturity_date <= %(to_date)s")
        values["to_date"] = filters["to_date"]

    where = " AND ".join(conditions)
    rows = frappe.db.sql(
        f"""
        SELECT
            boe.name AS bill_no,
            boe.bill_type,
            seg.segment_no,
            seg.segment_from,
            seg.segment_to,
            seg.amount,
            seg.status,
            seg.holder,
            seg.holder_type,
            boe.maturity_date,
            boe.drawer_name,
            boe.drawee_bank
        FROM `tabBill of Exchange` boe
        INNER JOIN `tabBill Segment` seg ON seg.parent = boe.name
        WHERE {where}
        ORDER BY boe.maturity_date ASC, boe.name, seg.idx
        """,
        values,
        as_dict=True,
    )
    return rows
