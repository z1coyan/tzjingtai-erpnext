# Copyright (c) 2026, 台州京泰 and contributors
# For license information, please see license.txt

import frappe
from frappe import _

from erpnext.accounts.general_ledger import make_gl_entries
from erpnext.controllers.accounts_controller import AccountsController


class BillPayment(AccountsController):
	def validate(self):
		# AccountsController 需要 posting_date 来做 fiscal year 判断; 这里复用 payment_date.
		# 用 db.set_value 式的 set 而不是 self.posting_date=...
		# 避免 meta 未同步时 getattr 抛 AttributeError.
		if not self.get("posting_date"):
			self.set("posting_date", self.payment_date)
		# 历史数据迁移通道: flags.historical_import=True 时,跳过状态/金额校验,
		# 直接信任迁移工具传入的 payment_amount. 用于把老系统里借壳"宁波银行供应商"
		# 收到的承兑到期兑付款正规化为 Bill Payment 单据.
		if self.flags.get("historical_import"):
			return
		self.validate_bill_status()
		self.validate_payment_amount()

	def validate_bill_status(self):
		"""校验票据状态"""
		boe = frappe.get_doc("Bill of Exchange", self.bill_of_exchange)
		if boe.bill_status not in ("Received - Circulating", "Payment Pending"):
			frappe.throw(
				_("Only bills with status 'Received - Circulating' or 'Payment Pending' can be redeemed, current status: {0}").format(boe.bill_status)
			)

	def validate_payment_amount(self):
		"""校验兑付金额等于票面金额"""
		boe = frappe.get_doc("Bill of Exchange", self.bill_of_exchange)
		if abs(self.payment_amount - boe.bill_amount) > 0.001:
			frappe.throw(_("Payment amount must equal bill amount {0}").format(boe.bill_amount))

	def on_submit(self):
		boe = frappe.get_doc("Bill of Exchange", self.bill_of_exchange)

		# 更新票据状态
		boe.update_status("Settled")
		boe.update_circulation_flag("Ended")

		self.create_gl_entries()

	def on_cancel(self):
		self.ignore_linked_doctypes = ("GL Entry", "Payment Ledger Entry", "Stock Ledger Entry")
		self.create_gl_entries(cancel=True)
		# 恢复票据状态
		boe = frappe.get_doc("Bill of Exchange", self.bill_of_exchange)
		boe.update_status("Received - Circulating")
		boe.update_circulation_flag("Circulating")

	def create_gl_entries(self, cancel=False):
		"""生成会计凭证：借 银行存款 / 贷 应收票据"""
		if not self.bank_account or not self.notes_receivable_account:
			return

		cost_center = self.get("cost_center") or frappe.db.get_value("Company", self.company, "cost_center")

		gl_entries = []

		# 借：银行存款
		gl_entries.append(
			self.get_gl_dict(
				{
					"account": self.bank_account,
					"debit_in_account_currency": self.payment_amount,
					"debit": self.payment_amount,
					"against": self.notes_receivable_account,
					"cost_center": cost_center,
					"remarks": _("Bill Payment - {0}").format(self.bill_no),
				}
			)
		)

		# 贷：应收票据
		gl_entries.append(
			self.get_gl_dict(
				{
					"account": self.notes_receivable_account,
					"credit_in_account_currency": self.payment_amount,
					"credit": self.payment_amount,
					"against": self.bank_account,
					"cost_center": cost_center,
					"remarks": _("Bill Payment - {0}").format(self.bill_no),
				}
			)
		)

		if gl_entries:
			make_gl_entries(gl_entries, cancel=cancel)
