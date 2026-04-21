import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class PayrollAdjustment(Document):
    def validate(self):
        self._validate_period()
        self._recompute_totals()

    def _validate_period(self):
        if not self.period_year or not self.period_month:
            return
        try:
            int(self.period_year)
            int(self.period_month)
        except (TypeError, ValueError):
            frappe.throw(_("Period Year and Period Month must be integers"))

    def _recompute_totals(self):
        bonus = 0.0
        supp = 0.0
        total = 0.0
        emps: set[str] = set()
        for d in self.details:
            amt = flt(d.amount)
            if d.employee:
                emps.add(d.employee)
            if d.adjustment_type == "Bonus":
                bonus += amt
            else:
                supp += amt
            total += amt
        self.total_bonus = flt(bonus, 2)
        self.total_supplementary = flt(supp, 2)
        self.total_amount = flt(total, 2)
        self.total_employees = len(emps)

    def before_submit(self):
        if not self.details:
            frappe.throw(_("Cannot submit with empty details"))
        if not self.wage_expense_account or not self.payroll_payable_account:
            frappe.throw(_("Wage Expense Account and Payroll Payable Account are required to submit"))
        if self.wage_expense_account == self.payroll_payable_account:
            frappe.throw(_("Wage Expense Account and Payroll Payable Account must be different"))
        for d in self.details:
            if flt(d.amount) <= 0:
                frappe.throw(_("Row {0}: Amount must be greater than zero").format(d.idx))

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

    def _make_journal_entry(self) -> str:
        cost_center = self.cost_center or frappe.db.get_value("Company", self.company, "cost_center")
        total = flt(sum(flt(d.amount) for d in self.details), 2)

        accounts: list[dict] = []
        for d in self.details:
            accounts.append({
                "account": self.wage_expense_account,
                "debit_in_account_currency": flt(d.amount, 2),
                "credit_in_account_currency": 0,
                "party_type": "Employee",
                "party": d.employee,
                "cost_center": cost_center,
                "user_remark": _("{0} · {1} · {2}: {3}").format(
                    d.employee_name or d.employee,
                    d.department or "",
                    d.adjustment_type,
                    d.remark or "",
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
            "user_remark": _("Payroll Adjustment {0} · {1} ({2}-{3:02d})").format(
                self.name, self.title or "", self.period_year, int(self.period_month)
            ),
            "accounts": accounts,
        })
        je.flags.ignore_permissions = True
        je.insert()
        return je.name
