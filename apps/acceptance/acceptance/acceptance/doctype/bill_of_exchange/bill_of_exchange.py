# Copyright (c) 2026, 台州京泰 and contributors
# For license information, please see license.txt

import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, getdate, today


class BillofExchange(Document):
	def validate(self):
		self.validate_bill_no()
		self.set_bill_type_from_no()
		self.calculate_bill_amount()
		self.validate_dates()

	def validate_bill_no(self):
		"""校验票据包号：标准格式为 30 位数字、首位 5/6/7/8。
		为兼容期初历史数据导入，仅要求非空；不符合新格式的票据不自动推断类型。"""
		if not self.bill_no:
			frappe.throw(_("Bill number is required"))

	def set_bill_type_from_no(self):
		"""根据票据包号首位自动设置票据种类（仅在未显式指定 bill_type 时生效）"""
		if self.bill_type:
			return
		type_map = {
			"5": "Bank Acceptance Bill",
			"6": "Commercial Acceptance Bill",
			"7": "Supply Chain Commercial Bill",
			"8": "Supply Chain Bank Bill",
		}
		first_digit = self.bill_no[0] if self.bill_no else ""
		self.bill_type = type_map.get(first_digit, "Bank Acceptance Bill")

	def calculate_bill_amount(self):
		"""根据子票区间计算票面金额；区间为 0/空表示不可拆分或老票无子票"""
		ss = self.sub_ticket_start or 0
		se = self.sub_ticket_end or 0
		self.sub_ticket_start = ss
		self.sub_ticket_end = se
		if ss == 0 and se == 0:
			self.is_splittable = 0
		else:
			self.bill_amount = (se - ss + 1) * 0.01
			self.is_splittable = 1

	def validate_dates(self):
		"""校验到期日期不早于出票日期（期初数据允许相等）"""
		if self.issue_date and self.due_date:
			if getdate(self.due_date) < getdate(self.issue_date):
				frappe.throw(_("Due date must be on or after issue date"))

	def update_status(self, new_status):
		"""更新票据状态（由业务操作单据调用）"""
		self.db_set("bill_status", new_status)

	def update_circulation_flag(self, flag):
		"""更新流通标志"""
		self.db_set("circulation_flag", flag)

	def add_endorsement_record(self, endorser, endorsee, date, sub_start, sub_end, amount,
		endorsement_type=None, source_doctype=None, source_docname=None):
		"""向背书链条子表追加记录"""
		max_seq = 0
		for row in self.endorsement_chain:
			if row.sequence > max_seq:
				max_seq = row.sequence

		self.append("endorsement_chain", {
			"sequence": max_seq + 1,
			"endorsement_type": endorsement_type,
			"endorser_name": endorser,
			"endorsee_name": endorsee,
			"endorsement_date": date,
			"sub_start": sub_start,
			"sub_end": sub_end,
			"endorsement_amount": amount,
			"source_doctype": source_doctype,
			"source_docname": source_docname,
		})
		self.flags.ignore_validate_update_after_submit = True
		self.save(ignore_permissions=True)

	def remove_endorsement_record(self, source_doctype, source_docname):
		"""根据来源单据删除背书链条中对应的记录"""
		self.endorsement_chain = [
			row for row in self.endorsement_chain
			if not (row.source_doctype == source_doctype and row.source_docname == source_docname)
		]
		# 重新编号
		for idx, row in enumerate(self.endorsement_chain, start=1):
			row.sequence = idx
		self.flags.ignore_validate_update_after_submit = True
		self.save(ignore_permissions=True)

	def split_sub_ticket(self, split_amount):
		"""子票拆分算法

		参数:
			split_amount: 拆分金额（必须为0.01的整数倍）

		返回:
			(子票A区间, 子票B区间) 元组
			子票A = 拆分部分, 子票B = 剩余部分
		"""
		if not self.is_splittable:
			frappe.throw(_("This bill is non-splittable (sub ticket range is 0)"))

		# 校验金额为0.01的整数倍
		split_count = round(split_amount / 0.01)
		if abs(split_count * 0.01 - split_amount) > 0.001:
			frappe.throw(_("Split amount must be a multiple of 0.01"))

		total_count = self.sub_ticket_end - self.sub_ticket_start + 1
		if split_count >= total_count:
			frappe.throw(_("Split amount must be less than bill amount"))
		if split_count <= 0:
			frappe.throw(_("Split amount must be greater than 0"))

		# 生成两个子票区间
		sub_a_start = self.sub_ticket_start
		sub_a_end = self.sub_ticket_start + split_count - 1
		sub_b_start = self.sub_ticket_start + split_count
		sub_b_end = self.sub_ticket_end

		# 校验金额一致性
		amount_a = (sub_a_end - sub_a_start + 1) * 0.01
		amount_b = (sub_b_end - sub_b_start + 1) * 0.01
		if abs(amount_a + amount_b - self.bill_amount) > 0.001:
			frappe.throw(_("Total amount after split does not match original bill amount"))

		return (
			{"start": sub_a_start, "end": sub_a_end, "amount": amount_a},
			{"start": sub_b_start, "end": sub_b_end, "amount": amount_b},
		)


def check_bill_maturity():
	"""每日定时任务：检查即将到期的票据并发送提醒"""
	remind_days = 7  # 默认提前7天提醒

	target_date = add_days(today(), remind_days)

	bills = frappe.get_all(
		"Bill of Exchange",
		filters={
			"due_date": ["<=", target_date],
			"due_date": [">=", today()],
			"bill_status": ["in", ["Received - Circulating"]],
			"docstatus": 1,
		},
		fields=["name", "bill_no", "due_date", "bill_amount", "acceptor_name", "company"],
	)

	for bill in bills:
		days_remaining = (getdate(bill.due_date) - getdate(today())).days

		# 发送系统通知给有 Accounts User 角色的用户
		users = frappe.get_all(
			"Has Role",
			filters={"role": ["in", ["Accounts User", "Accounts Manager"]], "parenttype": "User"},
			fields=["parent"],
		)

		for user in users:
			frappe.publish_realtime(
				"msgprint",
				{
					"message": _("Bill {0} (Acceptor: {1}, Amount: {2}) will mature in {3} days").format(
						bill.bill_no, bill.acceptor_name, bill.bill_amount, days_remaining
					),
					"title": _("Bill Maturity Reminder"),
					"indicator": "orange",
				},
				user=user.parent,
			)
