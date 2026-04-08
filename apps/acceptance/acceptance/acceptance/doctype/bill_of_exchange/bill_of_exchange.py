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
		"""校验票据包号：30位数字，首位为5/6/7/8"""
		if not re.match(r"^[5678]\d{29}$", self.bill_no):
			frappe.throw(_("Bill number must be 30 digits starting with 5 (bank), 6 (commercial), 7 (supply chain commercial) or 8 (supply chain bank)"))

	def set_bill_type_from_no(self):
		"""根据票据包号首位自动设置票据种类"""
		type_map = {
			"5": "Bank Acceptance Bill",
			"6": "Commercial Acceptance Bill",
			"7": "Supply Chain Commercial Bill",
			"8": "Supply Chain Bank Bill",
		}
		first_digit = self.bill_no[0] if self.bill_no else ""
		if first_digit in type_map:
			self.bill_type = type_map[first_digit]

	def calculate_bill_amount(self):
		"""根据子票区间计算票面金额"""
		if self.sub_ticket_start == 0 and self.sub_ticket_end == 0:
			# 不可拆分票据，金额由用户手动输入
			self.is_splittable = 0
		else:
			self.bill_amount = (self.sub_ticket_end - self.sub_ticket_start + 1) * 0.01
			self.is_splittable = 1

	def validate_dates(self):
		"""校验到期日期必须晚于出票日期"""
		if self.issue_date and self.due_date:
			if getdate(self.due_date) <= getdate(self.issue_date):
				frappe.throw(_("Due date must be after issue date"))

	def update_status(self, new_status):
		"""更新票据状态（由业务操作单据调用）"""
		self.db_set("bill_status", new_status)

	def update_circulation_flag(self, flag):
		"""更新流通标志"""
		self.db_set("circulation_flag", flag)

	def add_endorsement_record(self, endorser, endorsee, date, sub_start, sub_end, amount, log_ref=None):
		"""向背书链条子表追加记录"""
		# 获取当前最大序号
		max_seq = 0
		for row in self.endorsement_chain:
			if row.sequence > max_seq:
				max_seq = row.sequence

		self.append("endorsement_chain", {
			"sequence": max_seq + 1,
			"endorser_name": endorser,
			"endorsee_name": endorsee,
			"endorsement_date": date,
			"sub_start": sub_start,
			"sub_end": sub_end,
			"endorsement_amount": amount,
			"endorsement_log": log_ref,
		})
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
