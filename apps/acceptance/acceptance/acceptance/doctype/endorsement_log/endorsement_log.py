# Copyright (c) 2026, 台州京泰 and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class EndorsementLog(Document):
	def on_submit(self):
		"""提交时向关联票据的背书链条追加记录"""
		if self.bill_of_exchange:
			boe = frappe.get_doc("Bill of Exchange", self.bill_of_exchange)
			boe.add_endorsement_record(
				endorser=self.endorser_name,
				endorsee=self.endorsee_name,
				date=self.endorsement_date,
				sub_start=self.sub_ticket_start,
				sub_end=self.sub_ticket_end,
				amount=self.endorsement_amount,
				log_ref=self.name,
			)
