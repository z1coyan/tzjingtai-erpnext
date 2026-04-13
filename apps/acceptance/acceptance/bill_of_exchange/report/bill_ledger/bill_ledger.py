"""Bill Ledger —— 单张主票的全流转历史。

过滤器: bill (必填) → 按时间线列出 Receipt / Transfer / Discount / Settlement 四种事件。
"""

from __future__ import annotations

import frappe
from frappe import _


def execute(filters=None):
    filters = filters or {}
    if not filters.get("bill"):
        frappe.throw(_("Bill of Exchange filter is required"))
    columns = _columns()
    data = _get_data(filters["bill"])
    return columns, data


def _columns():
    return [
        {"label": _("Date"), "fieldname": "posting_date", "fieldtype": "Date", "width": 120},
        {"label": _("Action"), "fieldname": "action", "fieldtype": "Data", "width": 130},
        {"label": _("Document"), "fieldname": "document", "fieldtype": "Dynamic Link", "options": "doctype", "width": 180},
        {"label": _("DocType"), "fieldname": "doctype", "fieldtype": "Data", "width": 140},
        {"label": _("Counter Party"), "fieldname": "party", "fieldtype": "Data", "width": 180},
        {"label": _("Amount"), "fieldname": "amount", "fieldtype": "Currency", "width": 120},
        {"label": _("Journal Entry"), "fieldname": "journal_entry", "fieldtype": "Link", "options": "Journal Entry", "width": 180},
    ]


def _get_data(bill: str):
    events = []

    receipts = frappe.get_all(
        "Bill Receipt",
        filters={"bill": bill, "docstatus": 1},
        fields=["name", "posting_date", "from_party_type", "from_party", "amount", "journal_entry"],
    )
    for r in receipts:
        events.append(
            {
                "posting_date": r.posting_date,
                "action": _("Received"),
                "document": r.name,
                "doctype": "Bill Receipt",
                "party": f"{r.from_party_type} / {r.from_party}",
                "amount": r.amount,
                "journal_entry": r.journal_entry,
            }
        )

    transfers = frappe.get_all(
        "Bill Transfer",
        filters={"bill": bill, "docstatus": 1},
        fields=["name", "posting_date", "to_party_type", "to_party", "purpose", "amount", "journal_entry"],
    )
    for t in transfers:
        events.append(
            {
                "posting_date": t.posting_date,
                "action": _("Transferred ({0})").format(t.purpose),
                "document": t.name,
                "doctype": "Bill Transfer",
                "party": f"{t.to_party_type} / {t.to_party}",
                "amount": t.amount,
                "journal_entry": t.journal_entry,
            }
        )

    discounts = frappe.get_all(
        "Bill Discount",
        filters={"bill": bill, "docstatus": 1},
        fields=["name", "posting_date", "discount_bank_account", "total_face_amount", "discount_interest", "net_amount", "journal_entry"],
    )
    for d in discounts:
        events.append(
            {
                "posting_date": d.posting_date,
                "action": _("Discounted (interest {0})").format(d.discount_interest),
                "document": d.name,
                "doctype": "Bill Discount",
                "party": d.discount_bank_account,
                "amount": d.total_face_amount,
                "journal_entry": d.journal_entry,
            }
        )

    settlements = frappe.get_all(
        "Bill Settlement",
        filters={"bill": bill, "docstatus": 1},
        fields=["name", "posting_date", "settlement_bank_account", "total_amount", "journal_entry"],
    )
    for s in settlements:
        events.append(
            {
                "posting_date": s.posting_date,
                "action": _("Settled"),
                "document": s.name,
                "doctype": "Bill Settlement",
                "party": s.settlement_bank_account,
                "amount": s.total_amount,
                "journal_entry": s.journal_entry,
            }
        )

    events.sort(key=lambda e: (e["posting_date"] or "", e["document"]))
    return events
