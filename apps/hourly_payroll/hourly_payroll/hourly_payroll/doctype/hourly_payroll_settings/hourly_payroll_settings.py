import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, getdate, today


class HourlyPayrollSettings(Document):
    def validate(self):
        if self.morning_end and self.morning_start and self.morning_end <= self.morning_start:
            frappe.throw(_("Morning End must be later than Morning Start"))
        if self.afternoon_end and self.afternoon_start and self.afternoon_end <= self.afternoon_start:
            frappe.throw(_("Afternoon End must be later than Afternoon Start"))
        if self.overtime_start and self.overtime_end and self.overtime_end <= self.overtime_start:
            frappe.throw(_("Overtime End must be later than Overtime Start"))
        if self.round_unit_hours and self.round_unit_hours <= 0:
            frappe.throw(_("Round Unit Hours must be positive"))
        if self.regular_hours_per_day and self.regular_hours_per_day <= 0:
            frappe.throw(_("Regular Hours Per Day must be positive"))

    @frappe.whitelist()
    def setup_shift_and_assignments(self, company: str | None = None):
        """幂等：根据 Settings 里的时间窗创建/更新 Shift Type，并把 Active 员工的
        default_shift 绑上。返回统计字典。"""
        name = (self.shift_type_name or "").strip() or "Hourly Payroll Shift"
        start_time = self.morning_start
        end_time = self.overtime_end or self.afternoon_end
        if not start_time or not end_time:
            frappe.throw(_("Morning Start and Afternoon End (or Overtime End) must be set first"))

        buffer = int(self.window_buffer_minutes or 0)
        process_after = self.shift_process_start_date or add_days(today(), -365)

        existed = frappe.db.exists("Shift Type", name)
        shift = frappe.get_doc("Shift Type", name) if existed else frappe.new_doc("Shift Type")
        shift.update({
            "name": name,
            "start_time": start_time,
            "end_time": end_time,
            "enable_auto_attendance": 1,
            "begin_check_in_before_shift_start_time": buffer,
            "allow_check_out_after_shift_end_time": buffer,
            "working_hours_calculation_based_on": "First Check-in and Last Check-out",
            "working_hours_threshold_for_half_day": 0,
            "working_hours_threshold_for_absent": 0,
            "process_attendance_after": getdate(process_after),
        })
        if existed:
            shift.save(ignore_permissions=True)
        else:
            shift.insert(ignore_permissions=True)

        filters: dict = {"status": "Active"}
        if company:
            filters["company"] = company
        employees = frappe.get_all("Employee", filters=filters, fields=["name", "default_shift"])

        bound = 0
        already = 0
        for emp in employees:
            if emp["default_shift"] == name:
                already += 1
                continue
            frappe.db.set_value("Employee", emp["name"], "default_shift", name, update_modified=False)
            bound += 1

        self.db_set("linked_shift_type", name)
        frappe.db.commit()

        return {
            "shift_type": name,
            "created": 0 if existed else 1,
            "updated": 1 if existed else 0,
            "employees_bound": bound,
            "employees_already_bound": already,
        }
