# Copyright (c) 2026, 台州京泰 and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import date_diff, getdate

from erpnext.accounts.general_ledger import make_gl_entries
from erpnext.controllers.accounts_controller import AccountsController

from acceptance.acceptance.accounting_defaults import (
	CLEARING_ACCOUNT,
	DISCOUNT_INTEREST_ACCOUNT,
	NOTES_RECEIVABLE_ACCOUNT,
)


class BillDiscount(AccountsController):
	def validate(self):
		# 历史数据迁移通道: flags.historical_import=True 时,跳过状态校验并信任
		# 外部传入的 discount_amount / discount_interest / actual_amount / remaining_days,
		# 避免 controller 按利率反算覆盖导致 1 分钱级别的浮点偏差与历史银行流水不符.
		if self.flags.get("historical_import"):
			return
		self._autofill_accounts()
		self._reject_real_bank_leaf()
		self.validate_bill_status()
		self.calculate_discount()

	def _autofill_accounts(self):
		"""未填写科目时自动带出默认值.

		bank_account 字段语义是"结算过渡账户", 强制默认为 11215 票据清算中
		而不是真正的银行叶子账户. 理由见 accounting_defaults.py 模块注释.
		"""
		if not self.bank_account:
			self.bank_account = CLEARING_ACCOUNT
		if not self.notes_receivable_account:
			self.notes_receivable_account = NOTES_RECEIVABLE_ACCOUNT
		if not self.interest_account:
			self.interest_account = DISCOUNT_INTEREST_ACCOUNT

	def _reject_real_bank_leaf(self):
		"""禁止把 bank_account 指向真实银行叶子账户 (account_type=Bank).

		如果允许, 本单据生成的 GL 会在银行科目上记一次, 后续每周导入的银行流水
		又会再记一次, 导致银行科目重复计账. 统一走清算中 → 银行流水导入阶段
		再从清算中贷方冲销, 自然对冲, 不会重复.
		"""
		if not self.bank_account:
			return
		acc_type = frappe.db.get_value("Account", self.bank_account, "account_type")
		if acc_type == "Bank":
			frappe.throw(
				_(
					"Bill Discount 的结算账户不能直接写真实银行叶子账户 {0}. "
					"请改成清算中账户 {1}, 等每周银行流水导入时再从清算中冲减, "
					"否则会与银行流水重复记账."
				).format(self.bank_account, CLEARING_ACCOUNT)
			)

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
		# 告诉 Frappe 忽略对 GL Entry / Payment Ledger Entry 的反向链接检查,
		# 否则 "总账分录关联, 无法取消" 会拦住正常取消流程
		self.ignore_linked_doctypes = ("GL Entry", "Payment Ledger Entry", "Stock Ledger Entry")
		self.create_gl_entries(cancel=True)
		# 恢复票据状态
		boe = frappe.get_doc("Bill of Exchange", self.bill_of_exchange)
		boe.update_status("Received - Circulating")
		boe.update_circulation_flag("Circulating")

	def create_gl_entries(self, cancel=False):
		"""生成会计凭证：借 银行存款 + 借 财务费用-贴现利息 / 贷 应收票据"""
		if not self.bank_account or not self.notes_receivable_account or not self.interest_account:
			return

		# 损益类科目必须带成本中心; 优先用单据上的, 否则取公司默认
		cost_center = self.get("cost_center") or frappe.db.get_value("Company", self.company, "cost_center")

		gl_entries = []

		# 借：银行存款（实际到账金额）
		gl_entries.append(
			self.get_gl_dict(
				{
					"account": self.bank_account,
					"debit_in_account_currency": self.actual_amount,
					"debit": self.actual_amount,
					"against": self.notes_receivable_account,
					"cost_center": cost_center,
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
					"cost_center": cost_center,
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
					"cost_center": cost_center,
					"remarks": _("Bill Discount - {0}").format(self.bill_no),
				}
			)
		)

		if gl_entries:
			make_gl_entries(gl_entries, cancel=cancel)
