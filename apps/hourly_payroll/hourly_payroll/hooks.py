app_name = "hourly_payroll"
app_title = "Hourly Payroll"
app_publisher = "台州京泰"
app_description = "工时制薪资 —— 考勤导入 / 上下午加班三段工时 / 月度批量算薪"
app_email = "it@tzjingtai.com"
app_license = "MIT"

required_apps = ["erpnext", "hrms"]

doctype_js = {
    "Monthly Payroll Run": "public/js/monthly_payroll_run.js",
    "Attlog Import": "public/js/attlog_import.js",
    "Hourly Payroll Settings": "public/js/hourly_payroll_settings.js",
    "Payroll Adjustment": "public/js/payroll_adjustment.js",
}

doc_events = {
    "Attendance": {
        "before_save": "hourly_payroll.utils.work_hours.recalc_attendance_hours",
    },
}

fixtures = [
    {
        "dt": "Custom Field",
        "filters": [["name", "in", [
            "Employee-daily_wage",
            "Attendance-hourly_payroll_section",
            "Attendance-regular_hours",
            "Attendance-overtime_hours",
            "Attendance-net_work_hours",
        ]]],
    }
]
