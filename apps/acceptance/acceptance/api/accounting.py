"""Journal Entry 生成辅助 —— 四类承兑单据共用。

关键：Discount / Settlement 必须把 Bank Account + cheque_no + cheque_date 填上，
这样 ERPNext 原生 Bank Reconciliation Tool 在对账时能直接把这张 JE 和银行流水对上，
避免财务月末导入对账单后重复录入。
"""

from __future__ import annotations

import frappe
from frappe import _


def _get_bank_gl_account(bank_account: str | None) -> str | None:
    if not bank_account:
        return None
    return frappe.db.get_value("Bank Account", bank_account, "account")


def _get_party_account(party_type: str, party: str, company: str) -> str:
    if party_type == "Customer":
        from erpnext.accounts.party import get_party_account

        return get_party_account("Customer", party, company)
    if party_type == "Supplier":
        from erpnext.accounts.party import get_party_account

        return get_party_account("Supplier", party, company)
    frappe.throw(_("Unsupported party_type: {0}").format(party_type))


def create_journal_entry(
    *,
    company: str,
    posting_date,
    user_remark: str,
    lines: list[dict],
    bank_account: str | None = None,
    cheque_no: str | None = None,
    cheque_date=None,
) -> str:
    """创建并提交一张 Journal Entry，返回 name。

    lines 每行 dict：
      { account, debit_in_account_currency, credit_in_account_currency,
        party_type?, party?, reference_type?, reference_name? }
    """
    je = frappe.new_doc("Journal Entry")
    je.voucher_type = "Journal Entry"
    je.posting_date = posting_date
    je.company = company
    je.user_remark = user_remark
    if cheque_no:
        je.cheque_no = cheque_no
        je.cheque_date = cheque_date
    if bank_account:
        je.bank_account = bank_account
    for row in lines:
        je.append("accounts", row)
    je.insert(ignore_permissions=True)
    je.submit()
    return je.name


def cancel_journal_entry(name: str) -> None:
    if not name or not frappe.db.exists("Journal Entry", name):
        return
    je = frappe.get_doc("Journal Entry", name)
    if je.docstatus == 1:
        je.cancel()


def build_receipt_lines(receipt_doc, bill_doc) -> list[dict]:
    """Bill Receipt → JE 行。

    Customer:  Dr 应收票据   Cr 应收账款 (party=Customer)
    Supplier:  Dr 应收票据   Cr 应付账款 (party=Supplier)
    Opening:   Dr 应收票据   Cr 期初调整科目 (no party)
    """
    amount = receipt_doc.amount
    credit_line: dict = {
        "account": receipt_doc.credit_account,
        "debit_in_account_currency": 0,
        "credit_in_account_currency": amount,
    }
    if not receipt_doc.is_opening:
        credit_line["party_type"] = receipt_doc.from_party_type
        credit_line["party"] = receipt_doc.from_party
    lines = [
        {
            "account": receipt_doc.debit_account,
            "debit_in_account_currency": amount,
            "credit_in_account_currency": 0,
            "user_remark": _("Bill Receipt {0} · {1}").format(receipt_doc.name, bill_doc.bill_no),
        },
        credit_line,
    ]
    return lines


def build_transfer_lines(transfer_doc, bill_doc) -> list[dict]:
    """Bill Transfer → JE 行。

    to Supplier (Endorsement Out):    Dr 应付账款(party=Supplier)   Cr 应收票据
    to Customer (Refund / Penalty):   Dr 应收账款(party=Customer)   Cr 应收票据
    """
    amount = transfer_doc.amount
    lines = [
        {
            "account": transfer_doc.debit_account,
            "debit_in_account_currency": amount,
            "credit_in_account_currency": 0,
            "party_type": transfer_doc.to_party_type,
            "party": transfer_doc.to_party,
        },
        {
            "account": transfer_doc.credit_account,
            "debit_in_account_currency": 0,
            "credit_in_account_currency": amount,
            "user_remark": _("Bill Transfer {0} · {1}").format(transfer_doc.name, bill_doc.bill_no),
        },
    ]
    return lines


def build_discount_lines(discount_doc, bill_doc) -> list[dict]:
    """Bill Discount → JE 行。

    Dr Bank Cash Account   net_amount
    Dr Interest Account    discount_interest
       Cr Bill Receivable  total_face_amount
    """
    lines = [
        {
            "account": discount_doc.bank_cash_account,
            "debit_in_account_currency": discount_doc.net_amount,
            "credit_in_account_currency": 0,
            "user_remark": _("Bill Discount {0} · {1}").format(discount_doc.name, bill_doc.bill_no),
        },
        {
            "account": discount_doc.interest_account,
            "debit_in_account_currency": discount_doc.discount_interest,
            "credit_in_account_currency": 0,
        },
        {
            "account": discount_doc.bill_credit_account,
            "debit_in_account_currency": 0,
            "credit_in_account_currency": discount_doc.total_face_amount,
        },
    ]
    return lines


def build_settlement_lines(settlement_doc, bill_doc) -> list[dict]:
    """Bill Settlement → JE 行。

    Dr Bank Cash Account   total_amount
       Cr Bill Receivable  total_amount
    """
    amount = settlement_doc.total_amount
    lines = [
        {
            "account": settlement_doc.bank_cash_account,
            "debit_in_account_currency": amount,
            "credit_in_account_currency": 0,
            "user_remark": _("Bill Settlement {0} · {1}").format(settlement_doc.name, bill_doc.bill_no),
        },
        {
            "account": settlement_doc.bill_credit_account,
            "debit_in_account_currency": 0,
            "credit_in_account_currency": amount,
        },
    ]
    return lines


def resolve_party_account(party_type: str, party: str, company: str) -> str:
    return _get_party_account(party_type, party, company)


def resolve_bank_gl_account(bank_account: str | None) -> str | None:
    return _get_bank_gl_account(bank_account)
