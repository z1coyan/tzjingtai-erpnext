# Copyright (c) 2026, 台州京泰 and contributors
# For license information, please see license.txt

import frappe
from frappe import _

from erpnext.accounts.general_ledger import make_gl_entries
from erpnext.controllers.accounts_controller import AccountsController


class BillTransfer(AccountsController):
	def validate(self):
		self.validate_bill_status()
		self.validate_transfer_amount()
		self.calculate_split()

	def validate_bill_status(self):
		"""校验票据状态必须为可流通"""
		boe = frappe.get_doc("Bill of Exchange", self.bill_of_exchange)
		if boe.bill_status != "已收票-可流通":
			frappe.throw(_("只能转让状态为「已收票-可流通」的票据，当前状态为：{0}").format(boe.bill_status))

		if boe.no_transfer_mark:
			frappe.throw(_("该票据已标记「不得转让」，无法进行背书转让"))

	def validate_transfer_amount(self):
		"""校验转让金额"""
		boe = frappe.get_doc("Bill of Exchange", self.bill_of_exchange)

		if self.transfer_amount > boe.bill_amount:
			frappe.throw(_("转让金额不能大于票面金额"))

		if self.transfer_amount < boe.bill_amount:
			# 部分转让
			self.is_partial_transfer = 1
			if not boe.is_splittable:
				frappe.throw(_("该票据不可拆分，无法部分转让"))
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

	def on_submit(self):
		boe = frappe.get_doc("Bill of Exchange", self.bill_of_exchange)

		if self.is_partial_transfer:
			self.execute_split(boe)
		else:
			self.execute_full_transfer(boe)

		self.create_endorsement_log(boe)
		self.create_gl_entries()

	def execute_full_transfer(self, boe):
		"""整票转让"""
		boe.update_status("已背书转让")
		boe.update_circulation_flag("已结束")
		boe.db_set("current_holder", frappe.get_value("Supplier", self.supplier, "supplier_name") or self.supplier)

	def execute_split(self, boe):
		"""部分转让 - 执行子票拆分"""
		# 在原票据中添加子票记录
		boe.append("sub_tickets", {
			"sub_start": self.transfer_sub_start,
			"sub_end": self.transfer_sub_end,
			"sub_amount": self.transfer_amount,
			"sub_status": "已转让",
			"holder": frappe.get_value("Supplier", self.supplier, "supplier_name") or self.supplier,
			"related_doc_type": "Bill Transfer",
			"related_doc_name": self.name,
		})
		boe.append("sub_tickets", {
			"sub_start": self.remaining_sub_start,
			"sub_end": self.remaining_sub_end,
			"sub_amount": self.remaining_amount,
			"sub_status": "可流通",
			"holder": self.company,
		})

		# 标记原票据为已拆分
		boe.update_status("已拆分")
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
		new_boe.bill_status = "已收票-可流通"
		new_boe.circulation_flag = "可流通"
		new_boe.company = self.company
		new_boe.parent_bill = boe.name
		new_boe.insert(ignore_permissions=True)
		new_boe.submit()

		self.db_set("new_bill_of_exchange", new_boe.name)

	def create_endorsement_log(self, boe):
		"""创建背书记录"""
		log = frappe.new_doc("Endorsement Log")
		log.bill_of_exchange = self.bill_of_exchange
		log.bill_no = self.bill_no or boe.bill_no
		log.endorsement_type = "背书转让"
		log.endorser_name = self.company
		log.endorsee_name = frappe.get_value("Supplier", self.supplier, "supplier_name") or self.supplier
		log.endorsement_amount = self.transfer_amount
		log.endorsement_date = self.transfer_date
		log.no_transfer_mark = self.no_transfer_mark

		if self.is_partial_transfer:
			log.sub_ticket_start = self.transfer_sub_start
			log.sub_ticket_end = self.transfer_sub_end

		log.insert(ignore_permissions=True)
		log.submit()

	def create_gl_entries(self, cancel=False):
		"""生成会计凭证：借 应付账款 / 贷 应收票据"""
		if not self.accounts_payable_account or not self.notes_receivable_account:
			return

		gl_entries = []

		# 借：应付账款
		gl_entries.append(
			self.get_gl_dict(
				{
					"account": self.accounts_payable_account,
					"debit_in_account_currency": self.transfer_amount,
					"debit": self.transfer_amount,
					"against": self.notes_receivable_account,
					"party_type": "Supplier",
					"party": self.supplier,
					"remarks": _("票据转让 - {0}").format(self.bill_no),
				}
			)
		)

		# 贷：应收票据
		gl_entries.append(
			self.get_gl_dict(
				{
					"account": self.notes_receivable_account,
					"credit_in_account_currency": self.transfer_amount,
					"credit": self.transfer_amount,
					"against": self.accounts_payable_account,
					"remarks": _("票据转让 - {0}").format(self.bill_no),
				}
			)
		)

		if gl_entries:
			make_gl_entries(gl_entries, cancel=cancel)

	def on_cancel(self):
		self.create_gl_entries(cancel=True)
		# 恢复票据状态
		boe = frappe.get_doc("Bill of Exchange", self.bill_of_exchange)
		if not self.is_partial_transfer:
			boe.update_status("已收票-可流通")
			boe.update_circulation_flag("可流通")
