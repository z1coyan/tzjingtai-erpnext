from frappe.model.document import Document

from acceptance.utils.segments import recompute_bill_status


class BillofExchange(Document):
    def validate(self):
        recompute_bill_status(self)
