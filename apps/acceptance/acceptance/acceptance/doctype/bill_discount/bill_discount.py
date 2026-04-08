# Copyright (c) 2026, 台州京泰 and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import date_diff, getdate

from erpnext.accounts.general_ledger import make_gl_entries
from erpnext.controllers.accounts_controller import AccountsController


class BillDiscount(AccountsController):
	def validate(self):
		self.validate_bill_status()
		self.calculate_discount()

	def validate_bill_status(self):
		"""校验票据状态"""
		boe = frappe.get_doc("Bill of Exchange", self.bill_of_exchange)
		if boe.bill_status != "Received - Circulating":
			frappe.throw(_("Only bills with status 'Received - Circulating' can be discounted, current status: {0}").format(boe.bill_status))

	def calculate_discount(self):
		"""计算贴现利息和实际到账金额"""
		boe = frappe.get_doc("Bill of Exchange", self.bill_of_exchange)

		# 计算剩余天数
		self.remaining_days = date_diff(boe.due_date, getdate(self.discount_date))
		if self.remaining_days <= 0:
			frappe.throw(_("Discount date must be before due date"))

		# 如果未指定贴现金额，默认为票面金额（整票贴现）
		if not self.discount_amount:
			self.discount_amount = boe.bill_amount

		# 贴现利息 = 贴现金额 × 贴现利率 × 剩余天数 ÷ 360
		self.discount_interest = self.discount_amount * (self.discount_rate / 100) * self.remaining_days / 360

		# 实际到账金额 = 贴现金额 - 贴现利息
		self.actual_amount = self.discount_amount - self.discount_interest

	def on_submit(self):
		boe = frappe.get_doc("Bill of Exchange", self.bill_of_exchange)

		# 更新票据状态
		boe.update_status("Discounted")
		boe.update_circulation_flag("Ended")

		self.create_gl_entries()

	def on_cancel(self):
		self.create_gl_entries(cancel=True)
		# 恢复票据状态
		boe = frappe.get_doc("Bill of Exchange", self.bill_of_exchange)
		boe.update_status("Received - Circulating")
		boe.update_circulation_flag("Circulating")

	def create_gl_entries(self, cancel=False):
		"""生成会计凭证：借 银行存款 + 借 财务费用-贴现利息 / 贷 应收票据"""
		if not self.bank_account or not self.notes_receivable_account or not self.interest_account:
			return

		gl_entries = []

		# 借：银行存款（实际到账金额）
		gl_entries.append(
			self.get_gl_dict(
				{
					"account": self.bank_account,
					"debit_in_account_currency": self.actual_amount,
					"debit": self.actual_amount,
					"against": self.notes_receivable_account,
					"remarks": _("Bill Discount - {0}").format(self.bill_no),
				}
			)
		)

		# 借：财务费用-票据贴现利息
		gl_entries.append(
			self.get_gl_dict(
				{
					"account": self.interest_account,
					"debit_in_account_currency": self.discount_interest,
					"debit": self.discount_interest,
					"against": self.notes_receivable_account,
					"remarks": _("Bill Discount Interest - {0}").format(self.bill_no),
				}
			)
		)

		# 贷：应收票据（贴现金额）
		gl_entries.append(
			self.get_gl_dict(
				{
					"account": self.notes_receivable_account,
					"credit_in_account_currency": self.discount_amount,
					"credit": self.discount_amount,
					"against": self.bank_account,
					"remarks": _("Bill Discount - {0}").format(self.bill_no),
				}
			)
		)

		if gl_entries:
			make_gl_entries(gl_entries, cancel=cancel)
