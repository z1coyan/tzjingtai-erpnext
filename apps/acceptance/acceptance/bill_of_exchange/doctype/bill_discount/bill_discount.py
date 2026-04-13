import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from acceptance.api.accounting import (
    build_discount_lines,
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


class BillDiscount(Document):
    def validate(self):
        if not self.segments_discounted:
            frappe.throw(_("Discounted Segments cannot be empty"))
        self.total_face_amount = sum((r.amount or 0) for r in self.segments_discounted)
        if self.discount_interest is None:
            frappe.throw(_("Discount Interest is required"))
        self.net_amount = (self.total_face_amount or 0) - (self.discount_interest or 0)
        if self.net_amount < 0:
            frappe.throw(_("Discount interest exceeds face amount"))
        if self.discount_bank_account and not self.bank_cash_account:
            gl = resolve_bank_gl_account(self.discount_bank_account)
            if gl:
                self.bank_cash_account = gl

        if self.bill:
            bill_doc = frappe.get_doc("Bill of Exchange", self.bill)
            if is_legacy_bill(bill_doc):
                # 老票不允许拆分贴现，必须整张
                if len(self.segments_discounted) != 1:
                    frappe.throw(
                        _("Legacy bills cannot be split; provide exactly one row with the full amount")
                    )
                outstanding = flt(bill_doc.outstanding_amount)
                row_amount = flt(self.segments_discounted[0].amount)
                if abs(row_amount - outstanding) > 0.001:
                    frappe.throw(
                        _(
                            "Legacy bills cannot be split. Amount {0} must equal the current outstanding holding {1}."
                        ).format(row_amount, outstanding)
                    )
            else:
                for row in self.segments_discounted:
                    if not row.segment_from or not row.segment_to:
                        frappe.throw(
                            _("Segment From and Segment To are required for electronic bills")
                        )
                    validate_range_and_amount(row.segment_from, row.segment_to, row.amount)

    def on_submit(self):
        bill_doc = frappe.get_doc("Bill of Exchange", self.bill)
        legacy = is_legacy_bill(bill_doc)
        for row in self.segments_discounted:
            if legacy:
                remove_legacy_row(bill_doc, row.amount)
            else:
                remove_electronic_range(bill_doc, row.segment_from, row.segment_to)
        recompute_bill_status(bill_doc)
        bill_doc.save(ignore_permissions=True)

        je_name = create_journal_entry(
            company=self.company,
            posting_date=self.posting_date,
            user_remark=_("Bill Discount {0}").format(self.name),
            lines=build_discount_lines(self, bill_doc),
            bank_account=self.discount_bank_account,
            cheque_no=self.bank_reference_no,
            cheque_date=self.bank_reference_date,
        )
        self.db_set("journal_entry", je_name)

    def on_cancel(self):
        bill_doc = frappe.get_doc("Bill of Exchange", self.bill)
        legacy = is_legacy_bill(bill_doc)
        for row in self.segments_discounted:
            if legacy:
                add_legacy_row(bill_doc, row.amount)
            else:
                add_electronic_range(bill_doc, row.segment_from, row.segment_to)
        recompute_bill_status(bill_doc)
        bill_doc.save(ignore_permissions=True)
        cancel_journal_entry(self.journal_entry)
