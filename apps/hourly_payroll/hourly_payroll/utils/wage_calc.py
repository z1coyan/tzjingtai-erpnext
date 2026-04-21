"""
月度薪资汇总：直接从 Employee Checkin 按员工+日期聚合算工时，不依赖 Attendance。

这样导入打卡数据后立刻能算薪，不需要配置 Shift Type / Shift Assignment /
Process Auto Attendance 定时任务。Attendance 上的三个工时 custom field 仍由
before_save 钩子维护（原生考勤报表可用），但薪资计算与 Attendance 解耦。
"""

from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date as date_type, datetime

import frappe
from frappe.utils import flt, get_datetime

from hourly_payroll.utils.work_hours import compute_day_hours


def aggregate(
    year: int,
    month: int,
    company: str,
    department: str | None = None,
    employee: str | None = None,
) -> list[dict]:
    """返回每个员工一行：{employee, employee_name, department, days_present,
    regular_hours, overtime_hours, total_hours, daily_wage, hourly_rate, amount}"""
    start, end = _month_range(year, month)
    settings = frappe.get_cached_doc("Hourly Payroll Settings")
    hours_per_day = flt(settings.regular_hours_per_day) or 8.0

    employees = _list_employees(company, department, employee)
    if not employees:
        return []
    emp_names = [e["name"] for e in employees]
    emp_meta = {e["name"]: e for e in employees}

    checkin_rows = frappe.get_all(
        "Employee Checkin",
        filters={
            "employee": ["in", emp_names],
            "time": ["between", [f"{start} 00:00:00", f"{end} 23:59:59"]],
        },
        fields=["employee", "time"],
        order_by="employee asc, time asc",
        limit_page_length=0,
    )

    by_emp_day: dict[str, dict[date_type, list[datetime]]] = defaultdict(lambda: defaultdict(list))
    for r in checkin_rows:
        ts = get_datetime(r["time"])
        by_emp_day[r["employee"]][ts.date()].append(ts)

    out: list[dict] = []
    for emp_name in emp_names:
        days = by_emp_day.get(emp_name) or {}
        if not days:
            continue
        reg_total = 0.0
        ot_total = 0.0
        days_present = 0
        for day, times in days.items():
            reg, ot = compute_day_hours(sorted(times), day, settings)
            if reg + ot > 0:
                days_present += 1
            reg_total += reg
            ot_total += ot
        total_hours = reg_total + ot_total
        meta = emp_meta[emp_name]
        daily_wage = flt(meta.get("daily_wage"))
        hourly_rate = daily_wage / hours_per_day if hours_per_day else 0.0
        work_days = total_hours / hours_per_day if hours_per_day else 0.0
        basic_wage = flt(work_days * daily_wage, 2)
        out.append({
            "employee": emp_name,
            "employee_name": meta.get("employee_name"),
            "attendance_device_id": meta.get("attendance_device_id"),
            "department": meta.get("department"),
            "days_present": days_present,
            "regular_hours": reg_total,
            "overtime_hours": ot_total,
            "total_hours": total_hours,
            "work_days": flt(work_days, 2),
            "daily_wage": daily_wage,
            "hourly_rate": hourly_rate,
            "basic_wage": basic_wage,
            "bonus": 0.0,
            "supplementary": 0.0,
            "amount": basic_wage,
        })

    out.sort(key=lambda r: (r["department"] or "", r["employee_name"] or "", r["employee"]))
    return out


def _month_range(year: int, month: int) -> tuple[date_type, date_type]:
    last_day = calendar.monthrange(year, month)[1]
    return date_type(year, month, 1), date_type(year, month, last_day)


def _list_employees(company: str, department: str | None, employee: str | None) -> list[dict]:
    filters: dict = {"company": company, "status": "Active"}
    if department:
        filters["department"] = department
    if employee:
        filters["name"] = employee
    return frappe.get_all(
        "Employee",
        filters=filters,
        fields=["name", "employee_name", "department", "daily_wage", "attendance_device_id"],
        limit_page_length=0,
    )
