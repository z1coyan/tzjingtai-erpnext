import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from acceptance.api.accounting import (
    build_transfer_lines,
    cancel_journal_entry,
    create_journal_entry,
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


class BillTransfer(Document):
    def validate(self):
        if not self.amount or self.amount <= 0:
            frappe.throw(_("Amount must be greater than zero"))
        if self.bill:
            bill_doc = frappe.get_doc("Bill of Exchange", self.bill)
            if is_legacy_bill(bill_doc):
                # 老票不允许拆分转让，必须整张
                outstanding = flt(bill_doc.outstanding_amount)
                if abs(flt(self.amount) - outstanding) > 0.001:
                    frappe.throw(
                        _(
                            "Legacy bills cannot be split. Amount {0} must equal the current outstanding holding {1}."
                        ).format(self.amount, outstanding)
                    )
            else:
                if not self.segment_from or not self.segment_to:
                    frappe.throw(
                        _("Segment From and Segment To are required for electronic bills")
                    )
                validate_range_and_amount(self.segment_from, self.segment_to, self.amount)

    def on_submit(self):
        bill_doc = frappe.get_doc("Bill of Exchange", self.bill)
        if is_legacy_bill(bill_doc):
            remove_legacy_row(bill_doc, self.amount)
        else:
            remove_electronic_range(bill_doc, self.segment_from, self.segment_to)
        recompute_bill_status(bill_doc)
        bill_doc.save(ignore_permissions=True)

        je_name = create_journal_entry(
            company=self.company,
            posting_date=self.posting_date,
            user_remark=_("Bill Transfer {0}").format(self.name),
            lines=build_transfer_lines(self, bill_doc),
        )
        self.db_set("journal_entry", je_name)

    def on_cancel(self):
        bill_doc = frappe.get_doc("Bill of Exchange", self.bill)
        if is_legacy_bill(bill_doc):
            add_legacy_row(bill_doc, self.amount)
        else:
            add_electronic_range(bill_doc, self.segment_from, self.segment_to)
        recompute_bill_status(bill_doc)
        bill_doc.save(ignore_permissions=True)
        cancel_journal_entry(self.journal_entry)
