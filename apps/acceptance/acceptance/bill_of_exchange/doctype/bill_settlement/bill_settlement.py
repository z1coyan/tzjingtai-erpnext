import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from acceptance.api.accounting import (
    build_settlement_lines,
    cancel_journal_entry,
    create_journal_entry,
    resolve_bank_gl_account,
)
from acceptance.utils.segments import (
    add_electronic_range,
    add_legacy_row,
    is_legacy_bill,
    recompute_bill_status,
    remove_electronic_range,
    remove_legacy_row,
    validate_range_and_amount,
)


class BillSettlement(Document):
    def validate(self):
        if not self.segments_settled:
            frappe.throw(_("Settled Segments cannot be empty"))
        self.total_amount = sum((r.amount or 0) for r in self.segments_settled)
        if self.settlement_bank_account and not self.bank_cash_account:
            gl = resolve_bank_gl_account(self.settlement_bank_account)
            if gl:
                self.bank_cash_account = gl

        if self.bill:
            bill_doc = frappe.get_doc("Bill of Exchange", self.bill)
            if is_legacy_bill(bill_doc):
                if len(self.segments_settled) != 1:
                    frappe.throw(
                        _("Legacy bills cannot be split; provide exactly one row with the full amount")
                    )
                outstanding = flt(bill_doc.outstanding_amount)
                row_amount = flt(self.segments_settled[0].amount)
                if abs(row_amount - outstanding) > 0.001:
                    frappe.throw(
                        _(
                            "Legacy bills cannot be split. Amount {0} must equal the current outstanding holding {1}."
                        ).format(row_amount, outstanding)
                    )
            else:
                for row in self.segments_settled:
                    if not row.segment_from or not row.segment_to:
                        frappe.throw(
                            _("Segment From and Segment To are required for electronic bills")
                        )
                    validate_range_and_amount(row.segment_from, row.segment_to, row.amount)

    def on_submit(self):
        bill_doc = frappe.get_doc("Bill of Exchange", self.bill)
        legacy = is_legacy_bill(bill_doc)
        for row in self.segments_settled:
            if legacy:
                remove_legacy_row(bill_doc, row.amount)
            else:
                remove_electronic_range(bill_doc, row.segment_from, row.segment_to)
        recompute_bill_status(bill_doc)
        bill_doc.save(ignore_permissions=True)

        je_name = create_journal_entry(
            company=self.company,
            posting_date=self.posting_date,
            user_remark=_("Bill Settlement {0}").format(self.name),
            lines=build_settlement_lines(self, bill_doc),
            bank_account=self.settlement_bank_account,
            cheque_no=self.bank_reference_no,
            cheque_date=self.bank_reference_date,
        )
        self.db_set("journal_entry", je_name)

    def on_cancel(self):
        bill_doc = frappe.get_doc("Bill of Exchange", self.bill)
        legacy = is_legacy_bill(bill_doc)
        for row in self.segments_settled:
            if legacy:
                add_legacy_row(bill_doc, row.amount)
            else:
                add_electronic_range(bill_doc, row.segment_from, row.segment_to)
        recompute_bill_status(bill_doc)
        bill_doc.save(ignore_permissions=True)
        cancel_journal_entry(self.journal_entry)
