# Copyright (c) 2026, 台州京泰 and contributors
# For license information, please see license.txt

import frappe
from frappe import _

from erpnext.accounts.party import get_party_account
from erpnext.controllers.accounts_controller import AccountsController


class BillTransfer(AccountsController):
	def validate(self):
		self.validate_bill_status()
		self.validate_transfer_amount()
		self.calculate_split()
		self.set_linked_invoice_type()

	def validate_bill_status(self):
		"""校验票据状态必须为可流通"""
		boe = frappe.get_doc("Bill of Exchange", self.bill_of_exchange)
		if boe.bill_status != "Received - Circulating":
			frappe.throw(_("Only bills with status 'Received - Circulating' can be transferred, current status: {0}").format(boe.bill_status))

		if boe.no_transfer_mark:
			frappe.throw(_("This bill is marked as 'No Transfer', endorsement transfer is not allowed"))

	def validate_transfer_amount(self):
		"""校验转让金额"""
		boe = frappe.get_doc("Bill of Exchange", self.bill_of_exchange)

		if self.transfer_amount > boe.bill_amount:
			frappe.throw(_("Transfer amount cannot exceed bill amount"))

		if self.transfer_amount < boe.bill_amount:
			# 部分转让
			self.is_partial_transfer = 1
			if not boe.is_splittable:
				frappe.throw(_("This bill is non-splittable, partial transfer is not allowed"))
		else:
			self.is_partial_transfer = 0

	def calculate_split(self):
		"""计算子票拆分方案"""
		if not self.is_partial_transfer:
			return

		boe = frappe.get_doc("Bill of Exchange", self.bill_of_exchange)
		sub_a, sub_b = boe.split_sub_ticket(self.transfer_amount)

		self.transfer_sub_start = sub_a["start"]
		self.transfer_sub_end = sub_a["end"]
		self.remaining_sub_start = sub_b["start"]
		self.remaining_sub_end = sub_b["end"]
		self.remaining_amount = sub_b["amount"]

	def set_linked_invoice_type(self):
		"""根据 party_type 自动设置关联发票类型"""
		if self.party_type == "Customer":
			self.linked_invoice_type = "Sales Invoice"
		elif self.party_type == "Supplier":
			self.linked_invoice_type = "Purchase Invoice"

	def on_submit(self):
		boe = frappe.get_doc("Bill of Exchange", self.bill_of_exchange)

		if self.is_partial_transfer:
			self.execute_split(boe)
		else:
			self.execute_full_transfer(boe)

		self.add_endorsement_to_boe(boe)
		self.create_journal_entry()

	def execute_full_transfer(self, boe):
		"""整票转让"""
		party_name_field = "customer_name" if self.party_type == "Customer" else "supplier_name"

		boe.update_status("Endorsed")
		boe.update_circulation_flag("Ended")
		boe.db_set("current_holder", frappe.get_value(self.party_type, self.party, party_name_field) or self.party)

	def execute_split(self, boe):
		"""部分转让 - 执行子票拆分"""
		party_name_field = "customer_name" if self.party_type == "Customer" else "supplier_name"
		party_display_name = frappe.get_value(self.party_type, self.party, party_name_field) or self.party

		# 在原票据中添加子票记录
		boe.append("sub_tickets", {
			"sub_start": self.transfer_sub_start,
			"sub_end": self.transfer_sub_end,
			"sub_amount": self.transfer_amount,
			"sub_status": "Transferred",
			"holder": party_display_name,
			"related_doc_type": "Bill Transfer",
			"related_doc_name": self.name,
		})
		boe.append("sub_tickets", {
			"sub_start": self.remaining_sub_start,
			"sub_end": self.remaining_sub_end,
			"sub_amount": self.remaining_amount,
			"sub_status": "Circulating",
			"holder": self.company,
		})

		# 标记原票据为已拆分
		boe.update_status("Split")
		boe.save(ignore_permissions=True)

		# 创建新票据（剩余部分，保持可流通）
		new_boe = frappe.new_doc("Bill of Exchange")
		new_boe.bill_no = boe.bill_no
		new_boe.bill_type = boe.bill_type
		new_boe.sub_ticket_start = self.remaining_sub_start
		new_boe.sub_ticket_end = self.remaining_sub_end
		new_boe.bill_amount = self.remaining_amount
		new_boe.issue_date = boe.issue_date
		new_boe.due_date = boe.due_date
		new_boe.drawer_name = boe.drawer_name
		new_boe.drawer_account = boe.drawer_account
		new_boe.drawer_bank = boe.drawer_bank
		new_boe.acceptor_name = boe.acceptor_name
		new_boe.acceptor_account = boe.acceptor_account
		new_boe.acceptor_bank = boe.acceptor_bank
		new_boe.payee_name = boe.payee_name
		new_boe.current_holder = self.company
		new_boe.bill_status = "Received - Circulating"
		new_boe.circulation_flag = "Circulating"
		new_boe.company = self.company
		new_boe.parent_bill = boe.name
		new_boe.insert(ignore_permissions=True)
		new_boe.submit()

		self.db_set("new_bill_of_exchange", new_boe.name)

	def add_endorsement_to_boe(self, boe):
		"""向票据台账的背书链条追加转让记录"""
		party_name_field = "customer_name" if self.party_type == "Customer" else "supplier_name"

		sub_start = self.transfer_sub_start if self.is_partial_transfer else boe.sub_ticket_start
		sub_end = self.transfer_sub_end if self.is_partial_transfer else boe.sub_ticket_end

		boe.add_endorsement_record(
			endorser=self.company,
			endorsee=frappe.get_value(self.party_type, self.party, party_name_field) or self.party,
			date=self.transfer_date,
			sub_start=sub_start,
			sub_end=sub_end,
			amount=self.transfer_amount,
			endorsement_type="Endorsement Transfer",
			source_doctype="Bill Transfer",
			source_docname=self.name,
		)

	def remove_endorsement_from_boe(self):
		"""取消时从票据台账的背书链条中移除对应记录"""
		if self.bill_of_exchange:
			boe = frappe.get_doc("Bill of Exchange", self.bill_of_exchange)
			if boe.docstatus == 1:
				boe.remove_endorsement_record("Bill Transfer", self.name)

	def create_journal_entry(self):
		"""生成 Journal Entry：借 应付账款或应收账款 / 贷 应收票据"""
		if not self.notes_receivable_account:
			return

		party_account = get_party_account(self.party_type, self.party, self.company)

		je = frappe.new_doc("Journal Entry")
		je.posting_date = self.transfer_date
		je.company = self.company
		je.voucher_type = "Journal Entry"
		je.user_remark = _("Bill Transfer - {0}").format(self.bill_no)

		# 借：应付账款(Supplier) 或 应收账款(Customer)
		debit_row = {
			"account": party_account,
			"debit_in_account_currency": self.transfer_amount,
			"party_type": self.party_type,
			"party": self.party,
		}
		if self.linked_invoice:
			debit_row["reference_type"] = self.linked_invoice_type
			debit_row["reference_name"] = self.linked_invoice
		je.append("accounts", debit_row)

		# 贷：应收票据
		je.append("accounts", {
			"account": self.notes_receivable_account,
			"credit_in_account_currency": self.transfer_amount,
		})

		je.insert(ignore_permissions=True)
		je.submit()

		self.db_set("journal_entry", je.name)
		frappe.msgprint(_("Journal Entry created: {0}").format(je.name))

	def cancel_journal_entry(self):
		"""取消关联的日记账分录"""
		if self.journal_entry:
			je = frappe.get_doc("Journal Entry", self.journal_entry)
			if je.docstatus == 1:
				je.flags.ignore_links = True
				je.cancel()

	def on_cancel(self):
		self.cancel_journal_entry()
		self.remove_endorsement_from_boe()
		# 恢复票据状态
		boe = frappe.get_doc("Bill of Exchange", self.bill_of_exchange)
		if not self.is_partial_transfer:
			boe.update_status("Received - Circulating")
			boe.update_circulation_flag("Circulating")
