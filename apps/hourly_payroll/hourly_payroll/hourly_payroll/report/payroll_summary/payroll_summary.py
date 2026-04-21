"""
Payroll Summary —— 按员工汇总某公司某年某月（或某年全年）的薪资总发放。

数据源：
  - Monthly Payroll Run (docstatus<2) 的 Monthly Payroll Detail
  - Payroll Adjustment   (docstatus<2) 的 Payroll Adjustment Detail (Bonus / Supplementary)

每个员工一行，金额展示为：
  基本工资 + (月内奖金 + 调整单奖金) + (月内补发 + 调整单补发) = 总发放
"""

from __future__ import annotations

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters: dict | None = None):
    filters = filters or {}
    if not filters.get("company") or not filters.get("period_year"):
        frappe.throw(_("Please select Company and Period Year"))
    return _columns(), _data(filters)


def _columns():
    return [
        {"label": _("Employee"), "fieldname": "employee", "fieldtype": "Link", "options": "Employee", "width": 120},
        {"label": _("Employee Name"), "fieldname": "employee_name", "fieldtype": "Data", "width": 140},
        {"label": _("Attendance Device Id"), "fieldname": "attendance_device_id", "fieldtype": "Data", "width": 110},
        {"label": _("Department"), "fieldname": "department", "fieldtype": "Link", "options": "Department", "width": 140},
        {"label": _("Period"), "fieldname": "period", "fieldtype": "Data", "width": 90},
        {"label": _("Work Days"), "fieldname": "work_days", "fieldtype": "Float", "precision": 2, "width": 90},
        {"label": _("Basic Wage"), "fieldname": "basic_wage", "fieldtype": "Currency", "width": 120},
        {"label": _("Bonus"), "fieldname": "bonus", "fieldtype": "Currency", "width": 110},
        {"label": _("Supplementary"), "fieldname": "supplementary", "fieldtype": "Currency", "width": 110},
        {"label": _("Total Paid"), "fieldname": "total_paid", "fieldtype": "Currency", "width": 130},
    ]


def _data(filters: dict) -> list[dict]:
    year = int(filters["period_year"])
    month = int(filters["period_month"]) if filters.get("period_month") else None
    company = filters["company"]
    employee = filters.get("employee")
    department = filters.get("department")

    payroll_rows = _load_payroll_details(year, month, company, employee, department)
    adj_rows = _load_adjustment_details(year, month, company, employee, department)

    # (employee, period) 为主键聚合
    bucket: dict[tuple[str, str], dict] = {}
    for r in payroll_rows:
        key = (r["employee"], r["period"])
        b = _ensure(bucket, key, r)
        b["work_days"] += flt(r["work_days"])
        b["basic_wage"] += flt(r["basic_wage"])
        b["bonus"] += flt(r["bonus"])
        b["supplementary"] += flt(r["supplementary"])

    for r in adj_rows:
        key = (r["employee"], r["period"])
        b = _ensure(bucket, key, r)
        if r["adjustment_type"] == "Bonus":
            b["bonus"] += flt(r["amount"])
        else:
            b["supplementary"] += flt(r["amount"])

    data: list[dict] = []
    for (emp, period), b in bucket.items():
        b["total_paid"] = flt(b["basic_wage"] + b["bonus"] + b["supplementary"], 2)
        data.append(b)

    data.sort(key=lambda r: (r["period"], r["department"] or "", r["employee_name"] or "", r["employee"]))
    return data


def _ensure(bucket: dict, key: tuple, template: dict) -> dict:
    if key not in bucket:
        bucket[key] = {
            "employee": template["employee"],
            "employee_name": template.get("employee_name"),
            "attendance_device_id": template.get("attendance_device_id"),
            "department": template.get("department"),
            "period": key[1],
            "work_days": 0.0,
            "basic_wage": 0.0,
            "bonus": 0.0,
            "supplementary": 0.0,
        }
    return bucket[key]


def _load_payroll_details(year: int, month: int | None, company: str, employee: str | None, department: str | None):
    conditions = ["run.docstatus < 2", "run.company = %(company)s", "run.period_year = %(year)s"]
    values: dict = {"company": company, "year": year}
    if month:
        conditions.append("run.period_month = %(month)s")
        values["month"] = str(month)
    if employee:
        conditions.append("det.employee = %(employee)s")
        values["employee"] = employee
    if department:
        conditions.append("det.department = %(department)s")
        values["department"] = department

    return frappe.db.sql(
        f"""
        SELECT
            det.employee,
            det.employee_name,
            det.attendance_device_id,
            det.department,
            run.period_year,
            run.period_month,
            CONCAT(run.period_year, '-', LPAD(run.period_month, 2, '0')) AS period,
            det.work_days,
            det.basic_wage,
            det.bonus,
            det.supplementary
        FROM `tabMonthly Payroll Detail` det
        JOIN `tabMonthly Payroll Run` run ON det.parent = run.name
        WHERE {' AND '.join(conditions)}
        """,
        values,
        as_dict=True,
    )


def _load_adjustment_details(year: int, month: int | None, company: str, employee: str | None, department: str | None):
    conditions = ["adj.docstatus < 2", "adj.company = %(company)s", "adj.period_year = %(year)s"]
    values: dict = {"company": company, "year": year}
    if month:
        conditions.append("adj.period_month = %(month)s")
        values["month"] = str(month)
    if employee:
        conditions.append("det.employee = %(employee)s")
        values["employee"] = employee
    if department:
        conditions.append("det.department = %(department)s")
        values["department"] = department

    return frappe.db.sql(
        f"""
        SELECT
            det.employee,
            det.employee_name,
            det.attendance_device_id,
            det.department,
            adj.period_year,
            adj.period_month,
            CONCAT(adj.period_year, '-', LPAD(adj.period_month, 2, '0')) AS period,
            det.adjustment_type,
            det.amount
        FROM `tabPayroll Adjustment Detail` det
        JOIN `tabPayroll Adjustment` adj ON det.parent = adj.name
        WHERE {' AND '.join(conditions)}
        """,
        values,
        as_dict=True,
    )
