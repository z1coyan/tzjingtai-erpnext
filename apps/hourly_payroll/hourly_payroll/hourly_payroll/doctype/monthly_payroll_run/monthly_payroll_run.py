import calendar
from datetime import date as date_type

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt
from frappe.utils.xlsxutils import build_xlsx_response

from hourly_payroll.utils.wage_calc import aggregate


class MonthlyPayrollRun(Document):
    def validate(self):
        self._validate_period()
        self._validate_unique_per_month()
        self._recompute_details_and_totals()

    def _validate_period(self):
        if not self.period_year or not self.period_month:
            return
        try:
            int(self.period_year)
            int(self.period_month)
        except (TypeError, ValueError):
            frappe.throw(_("Period Year and Period Month must be integers"))

    def _validate_unique_per_month(self):
        """同一公司 + 年 + 月 最多一条未取消的 Monthly Payroll Run。
        Amend 出来的修订单 (amended_from != None) 不算冲突，因为原单已 Cancelled。"""
        if not (self.company and self.period_year and self.period_month):
            return
        existing = frappe.db.get_all(
            "Monthly Payroll Run",
            filters={
                "company": self.company,
                "period_year": self.period_year,
                "period_month": self.period_month,
                "docstatus": ["<", 2],
                "name": ["!=", self.name or ""],
            },
            fields=["name"],
            limit_page_length=1,
        )
        if existing:
            frappe.throw(
                _("A Monthly Payroll Run for {0} {1}-{2:02d} already exists: {3}").format(
                    self.company, self.period_year, int(self.period_month), existing[0]["name"]
                )
            )

    def _recompute_details_and_totals(self):
        """根据每行 basic_wage + adjustment 重算 amount；然后刷新表头合计。"""
        total_reg = 0.0
        total_ot = 0.0
        total_amt = 0.0
        for d in self.details:
            d.amount = flt(flt(d.basic_wage) + flt(d.adjustment), 2)
            total_reg += flt(d.regular_hours)
            total_ot += flt(d.overtime_hours)
            total_amt += flt(d.amount)
        self.total_regular_hours = total_reg
        self.total_overtime_hours = total_ot
        self.total_amount = flt(total_amt, 2)
        self.total_employees = len(self.details)

    def before_submit(self):
        if not self.details:
            frappe.throw(_("Cannot submit an empty payroll run. Click Generate first."))
        if not self.wage_expense_account or not self.payroll_payable_account:
            frappe.throw(_("Wage Expense Account and Payroll Payable Account are required to submit"))
        if self.wage_expense_account == self.payroll_payable_account:
            frappe.throw(_("Wage Expense Account and Payroll Payable Account must be different"))
        if not self.posting_date:
            self.posting_date = _month_end(int(self.period_year), int(self.period_month))

    def on_submit(self):
        je_name = self._make_journal_entry()
        self.db_set("journal_entry", je_name)
        self.db_set("status", "Submitted")

    def on_cancel(self):
        if self.journal_entry and frappe.db.exists("Journal Entry", self.journal_entry):
            je = frappe.get_doc("Journal Entry", self.journal_entry)
            je.flags.ignore_permissions = True
            if je.docstatus == 0:
                je.delete()
            elif je.docstatus == 1:
                je.cancel()
        self.db_set("status", "Cancelled")

    @frappe.whitelist()
    def generate(self):
        if self.docstatus != 0:
            frappe.throw(_("Only Draft payroll runs can be regenerated"))

        rows = aggregate(
            year=int(self.period_year),
            month=int(self.period_month),
            company=self.company,
            department=self.department or None,
            employee=self.employee or None,
        )

        # 保留已存在行上用户手填的 adjustment（按 employee 对齐）
        preserved: dict[str, float] = {
            d.employee: flt(d.adjustment) for d in self.details if d.employee
        }

        self.set("details", [])
        for r in rows:
            self.append("details", {
                "employee": r["employee"],
                "employee_name": r["employee_name"],
                "attendance_device_id": r.get("attendance_device_id"),
                "department": r["department"],
                "days_present": r["days_present"],
                "regular_hours": r["regular_hours"],
                "overtime_hours": r["overtime_hours"],
                "total_hours": r["total_hours"],
                "work_days": r["work_days"],
                "daily_wage": r["daily_wage"],
                "hourly_rate": r["hourly_rate"],
                "basic_wage": r["basic_wage"],
                "adjustment": preserved.get(r["employee"], 0.0),
                # amount 在 validate() 里重算
            })

        self.status = "Generated" if rows else "Draft"
        if not self.posting_date and self.period_year and self.period_month:
            self.posting_date = _month_end(int(self.period_year), int(self.period_month))
        if not self.cost_center and self.company:
            self.cost_center = frappe.db.get_value("Company", self.company, "cost_center")
        self.save()

        return {
            "employees": len(rows),
            "total_amount": self.total_amount,
        }

    def _make_journal_entry(self) -> str:
        """按员工分行生成 Draft JE：
        - 每个 detail 一行 Dr 工资费用，金额 = basic_wage + adjustment
          借方不绑 Employee（ERPNext 要求绑 party 的账户必须是 Receivable/Payable），
          员工信息保留在 user_remark 里供审计追溯。
        - 合并一行 Cr 应付工资 = 应发合计
        """
        payable_rows = [d for d in self.details if flt(d.amount) > 0]
        if not payable_rows:
            frappe.throw(_("No payable amount in details; nothing to post"))

        cost_center = self.cost_center or frappe.db.get_value("Company", self.company, "cost_center")
        total = flt(sum(flt(d.amount) for d in payable_rows), 2)

        accounts: list[dict] = []
        for d in payable_rows:
            accounts.append({
                "account": self.wage_expense_account,
                "debit_in_account_currency": flt(d.amount, 2),
                "credit_in_account_currency": 0,
                "cost_center": cost_center,
                "user_remark": _(
                    "{0} ({1}) · {2} · {3} hrs · basic {4} + adj {5}"
                ).format(
                    d.employee_name or d.employee,
                    d.employee,
                    d.department or "",
                    flt(d.total_hours, 2),
                    flt(d.basic_wage, 2),
                    flt(d.adjustment, 2),
                ),
            })
        accounts.append({
            "account": self.payroll_payable_account,
            "debit_in_account_currency": 0,
            "credit_in_account_currency": total,
            "cost_center": cost_center,
        })

        je = frappe.new_doc("Journal Entry")
        je.update({
            "voucher_type": "Journal Entry",
            "company": self.company,
            "posting_date": self.posting_date,
            "user_remark": _("Hourly Payroll Run {0} ({1}-{2:02d})").format(
                self.name, self.period_year, int(self.period_month)
            ),
            "accounts": accounts,
        })
        je.flags.ignore_permissions = True
        je.insert()
        return je.name


def _month_end(year: int, month: int) -> date_type:
    last_day = calendar.monthrange(year, month)[1]
    return date_type(year, month, last_day)


@frappe.whitelist()
def export_details_xlsx(name: str):
    """导出月度薪资明细为 xlsx，供财务给银行代发工资使用。

    - 权限：沿用 Monthly Payroll Run 的 read 权限。
    - 列：覆盖员工银行发放所需的全部字段（姓名/身份证号/开户银行/银行账号/金额），
      同时保留工时与基本工资，便于财务在同一文件里做核对。
    """
    doc = frappe.get_doc("Monthly Payroll Run", name)
    doc.check_permission("read")

    headers = [
        _("No."),
        _("Employee"),
        _("Employee Name"),
        _("Attendance Device Id"),
        _("ID Card No"),
        _("Bank Name"),
        _("Bank Account No"),
        _("Department"),
        _("Days Present"),
        _("Regular Hours"),
        _("Overtime Hours"),
        _("Total Hours"),
        _("Work Days"),
        _("Daily Wage"),
        _("Basic Wage"),
        _("Adjustment"),
        _("Amount"),
    ]

    rows: list[list] = [headers]
    for idx, d in enumerate(doc.details, start=1):
        rows.append([
            idx,
            d.employee,
            d.employee_name,
            d.attendance_device_id,
            d.id_card_no,
            d.bank_name,
            d.bank_ac_no,
            d.department,
            d.days_present,
            flt(d.regular_hours, 2),
            flt(d.overtime_hours, 2),
            flt(d.total_hours, 2),
            flt(d.work_days, 2),
            flt(d.daily_wage, 2),
            flt(d.basic_wage, 2),
            flt(d.adjustment, 2),
            flt(d.amount, 2),
        ])

    # 合计行，便于与银行发放金额对账
    rows.append([
        "",
        "",
        _("Total"),
        "",
        "",
        "",
        "",
        "",
        "",
        flt(doc.total_regular_hours, 2),
        flt(doc.total_overtime_hours, 2),
        "",
        "",
        "",
        "",
        "",
        flt(doc.total_amount, 2),
    ])

    filename = f"{doc.name}-{doc.period_year}-{int(doc.period_month):02d}"
    build_xlsx_response(rows, filename)
