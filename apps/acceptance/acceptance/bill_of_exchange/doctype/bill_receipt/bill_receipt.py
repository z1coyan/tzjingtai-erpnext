import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from acceptance.api.accounting import (
    build_receipt_lines,
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


class BillReceipt(Document):
    def validate(self):
        self._resolve_bill()
        self._validate_segment()
        self._validate_opening()

    def on_submit(self):
        bill_doc = self._get_or_create_bill()
        if is_legacy_bill(bill_doc):
            add_legacy_row(bill_doc, self.amount)
        else:
            add_electronic_range(bill_doc, self.segment_from, self.segment_to)
        recompute_bill_status(bill_doc)
        bill_doc.save(ignore_permissions=True)

        je_name = create_journal_entry(
            company=self.company,
            posting_date=self.posting_date,
            user_remark=_("Bill Receipt {0}").format(self.name),
            lines=build_receipt_lines(self, bill_doc),
        )
        self.db_set("bill", bill_doc.name)
        self.db_set("journal_entry", je_name)

    def on_cancel(self):
        if self.bill:
            bill_doc = frappe.get_doc("Bill of Exchange", self.bill)
            if is_legacy_bill(bill_doc):
                remove_legacy_row(bill_doc, self.amount)
            else:
                remove_electronic_range(bill_doc, self.segment_from, self.segment_to)
            if not bill_doc.segments:
                # 台账清空：如果这是此 bill 的唯一来源，把 bill 一起删掉
                other_receipts = frappe.db.count(
                    "Bill Receipt",
                    {"bill": bill_doc.name, "docstatus": 1, "name": ["!=", self.name]},
                )
                if other_receipts == 0:
                    bill_doc.delete(ignore_permissions=True)
                else:
                    recompute_bill_status(bill_doc)
                    bill_doc.save(ignore_permissions=True)
            else:
                recompute_bill_status(bill_doc)
                bill_doc.save(ignore_permissions=True)
        cancel_journal_entry(self.journal_entry)

    def _resolve_bill(self):
        if not self.bill_no:
            return
        existing = frappe.db.exists("Bill of Exchange", {"bill_no": self.bill_no})
        if existing:
            self.is_new_bill = 0
            master = frappe.get_doc("Bill of Exchange", existing)
            self.face_amount = master.face_amount
            self.bill_type = master.bill_type
            self.is_electronic = master.is_electronic
            self.is_legacy = master.is_legacy
            self.drawer_name = master.drawer_name
            self.drawer_account_no = master.drawer_account_no
            self.drawee_bank = master.drawee_bank
            self.payee_name = master.payee_name
            self.issue_date = master.issue_date
            self.maturity_date = master.maturity_date
        else:
            self.is_new_bill = 1

    def _validate_segment(self):
        if not self.amount or self.amount <= 0:
            frappe.throw(_("Amount must be greater than zero"))
        if self.face_amount and flt(self.amount) > flt(self.face_amount):
            frappe.throw(
                _("Amount {0} exceeds bill face amount {1}").format(
                    self.amount, self.face_amount
                )
            )
        legacy = bool(self.is_legacy) or not bool(self.is_electronic)
        if legacy:
            # 老票只能一次性整张接收，且同一 bill_no 不允许二次接收
            if not self.is_new_bill:
                frappe.throw(
                    _(
                        "Legacy bill {0} already exists. Legacy bills cannot be received more than once."
                    ).format(self.bill_no)
                )
            if flt(self.amount) != flt(self.face_amount):
                frappe.throw(
                    _("Legacy bills must be received in full: amount {0} must equal face amount {1}").format(
                        self.amount, self.face_amount
                    )
                )
            return
        if not self.segment_from or not self.segment_to:
            frappe.throw(_("Segment From and Segment To are required for electronic bills"))
        validate_range_and_amount(self.segment_from, self.segment_to, self.amount)

    def _validate_opening(self):
        if self.is_opening:
            self.from_party_type = None
            self.from_party = None
            self.purpose = "Opening Balance"
        elif self.purpose == "Opening Balance":
            frappe.throw(_("Purpose 'Opening Balance' requires Is Opening to be checked"))

    def _get_or_create_bill(self):
        if self.is_new_bill:
            bill_doc = frappe.new_doc("Bill of Exchange")
            bill_doc.bill_no = self.bill_no
            bill_doc.bill_type = self.bill_type
            bill_doc.is_electronic = self.is_electronic
            bill_doc.is_legacy = self.is_legacy
            bill_doc.drawer_name = self.drawer_name
            bill_doc.drawer_account_no = self.drawer_account_no
            bill_doc.drawee_bank = self.drawee_bank
            bill_doc.payee_name = self.payee_name
            bill_doc.issue_date = self.issue_date
            bill_doc.maturity_date = self.maturity_date
            bill_doc.face_amount = self.face_amount
            bill_doc.face_image = self.face_image
            bill_doc.back_image_initial = self.back_image
            bill_doc.status = "Active"
            bill_doc.insert(ignore_permissions=True)
            return bill_doc
        return frappe.get_doc(
            "Bill of Exchange",
            frappe.db.get_value("Bill of Exchange", {"bill_no": self.bill_no}),
        )
