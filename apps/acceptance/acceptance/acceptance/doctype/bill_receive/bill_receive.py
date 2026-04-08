# Copyright (c) 2026, 台州京泰 and contributors
# For license information, please see license.txt

import re

import frappe
from frappe import _
from frappe.utils import getdate

from erpnext.accounts.general_ledger import make_gl_entries
from erpnext.controllers.accounts_controller import AccountsController


class BillReceive(AccountsController):
	def validate(self):
		self.validate_bill_no()
		self.calculate_bill_amount()
		self.validate_dates()

	def validate_bill_no(self):
		"""校验票据包号格式"""
		if not re.match(r"^[5678]\d{29}$", self.bill_no):
			frappe.throw(_("Bill number must be 30 digits starting with 5/6/7/8"))

		# 校验子票区间
		if self.sub_ticket_start == 0 and self.sub_ticket_end == 0:
			frappe.msgprint(_("Sub ticket range is 0, this bill is non-splittable"))

	def calculate_bill_amount(self):
		"""根据子票区间计算票面金额"""
		if self.sub_ticket_start == 0 and self.sub_ticket_end == 0:
			pass  # 不可拆分票据，金额由用户手动输入
		else:
			self.bill_amount = (self.sub_ticket_end - self.sub_ticket_start + 1) * 0.01

	def validate_dates(self):
		"""校验到期日期必须晚于出票日期"""
		if self.issue_date and self.due_date:
			if getdate(self.due_date) <= getdate(self.issue_date):
				frappe.throw(_("Due date must be after issue date"))

	def on_submit(self):
		self.create_bill_of_exchange()
		self.create_endorsement_log()
		self.create_gl_entries()

	def on_cancel(self):
		self.cancel_bill_of_exchange()
		self.create_gl_entries(cancel=True)

	def create_bill_of_exchange(self):
		"""创建票据台账记录"""
		# 根据票据包号首位确定票据种类
		type_map = {
			"5": "Bank Acceptance Bill",
			"6": "Commercial Acceptance Bill",
			"7": "Supply Chain Commercial Bill",
			"8": "Supply Chain Bank Bill",
		}

		boe = frappe.new_doc("Bill of Exchange")
		boe.bill_no = self.bill_no
		boe.bill_type = self.bill_type or type_map.get(self.bill_no[0], "")
		boe.sub_ticket_start = self.sub_ticket_start
		boe.sub_ticket_end = self.sub_ticket_end
		boe.bill_amount = self.bill_amount
		boe.issue_date = self.issue_date
		boe.due_date = self.due_date
		boe.drawer_name = self.drawer_name
		boe.drawer_account = self.drawer_account
		boe.drawer_bank = self.drawer_bank
		boe.acceptor_name = self.acceptor_name
		boe.acceptor_account = self.acceptor_account
		boe.acceptor_bank = self.acceptor_bank
		boe.payee_name = self.customer
		boe.current_holder = self.company
		boe.bill_status = "Received - Circulating"
		boe.circulation_flag = "Circulating"
		boe.company = self.company
		boe.linked_sales_invoice = self.linked_sales_invoice
		boe.insert(ignore_permissions=True)
		boe.submit()

		self.db_set("bill_of_exchange", boe.name)
		frappe.msgprint(_("Bill of Exchange created: {0}").format(boe.name))

	def cancel_bill_of_exchange(self):
		"""取消关联的票据台账"""
		if self.bill_of_exchange:
			boe = frappe.get_doc("Bill of Exchange", self.bill_of_exchange)
			if boe.docstatus == 1:
				boe.cancel()

	def create_endorsement_log(self):
		"""创建背书记录"""
		log = frappe.new_doc("Endorsement Log")
		log.bill_of_exchange = self.bill_of_exchange
		log.bill_no = self.bill_no
		log.endorsement_type = "Endorsement Received"
		log.endorser_name = frappe.get_value("Customer", self.customer, "customer_name") or self.customer
		log.endorsee_name = self.company
		log.sub_ticket_start = self.sub_ticket_start
		log.sub_ticket_end = self.sub_ticket_end
		log.endorsement_amount = self.bill_amount
		log.endorsement_date = self.posting_date
		log.insert(ignore_permissions=True)
		log.submit()

	def create_gl_entries(self, cancel=False):
		"""生成会计凭证：借 应收票据 / 贷 应收账款"""
		if not self.notes_receivable_account or not self.accounts_receivable_account:
			return

		gl_entries = []

		# 借：应收票据
		gl_entries.append(
			self.get_gl_dict(
				{
					"account": self.notes_receivable_account,
					"debit_in_account_currency": self.bill_amount,
					"debit": self.bill_amount,
					"against": self.accounts_receivable_account,
					"remarks": _("Bill Receive - {0}").format(self.bill_no),
				}
			)
		)

		# 贷：应收账款
		gl_entries.append(
			self.get_gl_dict(
				{
					"account": self.accounts_receivable_account,
					"credit_in_account_currency": self.bill_amount,
					"credit": self.bill_amount,
					"against": self.notes_receivable_account,
					"party_type": "Customer",
					"party": self.customer,
					"remarks": _("Bill Receive - {0}").format(self.bill_no),
				}
			)
		)

		if gl_entries:
			make_gl_entries(gl_entries, cancel=cancel)
