# Copyright (c) 2026, 台州京泰 and contributors
# For license information, please see license.txt

import re

import frappe
from frappe import _
from frappe.utils import getdate

from erpnext.accounts.party import get_party_account
from erpnext.controllers.accounts_controller import AccountsController


class BillReceive(AccountsController):
	def validate(self):
		self.validate_bill_no()
		self.calculate_bill_amount()
		self.validate_dates()
		self.set_linked_invoice_type()

	def validate_bill_no(self):
		"""校验票据包号格式。
		标准格式为 30 位数字、首位 5/6/7/8；为兼容期初历史数据导入，仅要求非空。"""
		if not self.bill_no:
			frappe.throw(_("Bill number is required"))

		# 校验子票区间
		if (self.sub_ticket_start or 0) == 0 and (self.sub_ticket_end or 0) == 0:
			frappe.msgprint(_("Sub ticket range is 0, this bill is non-splittable"))

	def calculate_bill_amount(self):
		"""根据子票区间计算票面金额；区间为 0/空则保留用户输入金额"""
		ss = self.sub_ticket_start or 0
		se = self.sub_ticket_end or 0
		self.sub_ticket_start = ss
		self.sub_ticket_end = se
		if ss == 0 and se == 0:
			pass  # 不可拆分票据或老票无子票，金额由用户手动输入
		else:
			self.bill_amount = (se - ss + 1) * 0.01

	def validate_dates(self):
		"""校验到期日期必须晚于出票日期（期初数据允许相等）"""
		if self.issue_date and self.due_date:
			if getdate(self.due_date) < getdate(self.issue_date):
				frappe.throw(_("Due date must be on or after issue date"))

	def set_linked_invoice_type(self):
		"""根据 party_type 自动设置关联发票类型"""
		if self.party_type == "Customer":
			self.linked_invoice_type = "Sales Invoice"
		elif self.party_type == "Supplier":
			self.linked_invoice_type = "Purchase Invoice"

	def on_submit(self):
		self.create_bill_of_exchange()
		self.add_endorsement_to_boe()
		self.create_journal_entry()

	def on_cancel(self):
		self.remove_endorsement_from_boe()
		self.cancel_bill_of_exchange()
		self.cancel_journal_entry()

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
		boe.payee_name = self.party
		boe.current_holder = self.company
		boe.bill_status = "Received - Circulating"
		boe.circulation_flag = "Circulating"
		boe.company = self.company

		if self.linked_invoice_type == "Sales Invoice" and self.linked_invoice:
			boe.linked_sales_invoice = self.linked_invoice
		elif self.linked_invoice_type == "Purchase Invoice" and self.linked_invoice:
			boe.linked_purchase_invoice = self.linked_invoice

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

	def add_endorsement_to_boe(self):
		"""向票据台账的背书链条追加接收记录"""
		party_name_field = "customer_name" if self.party_type == "Customer" else "supplier_name"
		boe = frappe.get_doc("Bill of Exchange", self.bill_of_exchange)
		boe.add_endorsement_record(
			endorser=frappe.get_value(self.party_type, self.party, party_name_field) or self.party,
			endorsee=self.company,
			date=self.posting_date,
			sub_start=self.sub_ticket_start,
			sub_end=self.sub_ticket_end,
			amount=self.bill_amount,
			endorsement_type="Endorsement Received",
			source_doctype="Bill Receive",
			source_docname=self.name,
		)

	def remove_endorsement_from_boe(self):
		"""取消时从票据台账的背书链条中移除对应记录"""
		if self.bill_of_exchange:
			boe = frappe.get_doc("Bill of Exchange", self.bill_of_exchange)
			if boe.docstatus == 1:
				boe.remove_endorsement_record("Bill Receive", self.name)

	def create_journal_entry(self):
		"""生成 Journal Entry：借 应收票据 / 贷 应收账款或应付账款"""
		if not self.notes_receivable_account:
			return

		party_account = get_party_account(self.party_type, self.party, self.company)

		je = frappe.new_doc("Journal Entry")
		je.posting_date = self.posting_date
		je.company = self.company
		je.voucher_type = "Journal Entry"
		je.user_remark = _("Bill Receive - {0}").format(self.bill_no)

		# 借：应收票据
		je.append("accounts", {
			"account": self.notes_receivable_account,
			"debit_in_account_currency": self.bill_amount,
		})

		# 贷：应收账款(Customer) 或 应付账款(Supplier)
		credit_row = {
			"account": party_account,
			"credit_in_account_currency": self.bill_amount,
			"party_type": self.party_type,
			"party": self.party,
		}
		if self.linked_invoice:
			credit_row["reference_type"] = self.linked_invoice_type
			credit_row["reference_name"] = self.linked_invoice
		je.append("accounts", credit_row)

		je.insert(ignore_permissions=True)
		je.submit()

		self.db_set("journal_entry", je.name)
		frappe.msgprint(_("Journal Entry created: {0}").format(je.name))

	def cancel_journal_entry(self):
		"""取消关联的日记账分录"""
		if self.journal_entry:
			je = frappe.get_doc("Journal Entry", self.journal_entry)
			if je.docstatus == 1:
				# Bill Receive 本身还在 cancel 流程中, 它的 link 会让 JE 的 link check 失败; 绕过
				je.flags.ignore_links = True
				je.cancel()
