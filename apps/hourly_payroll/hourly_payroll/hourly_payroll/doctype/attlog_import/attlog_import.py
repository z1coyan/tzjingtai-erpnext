import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import today
from frappe.utils.file_manager import get_file

from hourly_payroll.utils.attlog_parser import parse_attlog

PLACEHOLDER_FIRST_NAME = "未知"
PLACEHOLDER_DOB = "2000-01-01"


class AttlogImport(Document):
    def validate(self):
        if self.auto_create_unknown and not self.default_company:
            frappe.throw(_("Default Company is required when Auto Create Unknown Employees is enabled"))

    @frappe.whitelist()
    def parse_and_create(self):
        """读取附件 → 解析 → 批量创建 Employee Checkin（可选：自动新建未知员工）"""
        if not self.attach_file:
            frappe.throw(_("Please attach an attlog file first"))
        if self.auto_create_unknown and not self.default_company:
            frappe.throw(_("Default Company is required when Auto Create Unknown Employees is enabled"))

        _, content = get_file(self.attach_file)
        text = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else content
        records = parse_attlog(text)

        emp_map = _build_device_id_map()
        total = len(records)
        created = 0
        duplicates = 0
        unmapped = 0
        created_emps = 0
        unmapped_ids: set[str] = set()
        log_lines: list[str] = []

        for rec in records:
            employee = emp_map.get(rec.user_id)
            if not employee and self.auto_create_unknown:
                try:
                    employee = _create_placeholder_employee(rec.user_id, self.default_company)
                    emp_map[rec.user_id] = employee
                    created_emps += 1
                    log_lines.append(
                        _("Created placeholder Employee {0} for device user id {1}").format(
                            employee, rec.user_id
                        )
                    )
                except Exception as exc:
                    log_lines.append(
                        f"Failed to auto-create employee for device id {rec.user_id}: {exc}"
                    )
            if not employee:
                unmapped += 1
                unmapped_ids.add(rec.user_id)
                continue
            if _checkin_exists(employee, rec.timestamp):
                duplicates += 1
                continue
            try:
                doc = frappe.get_doc({
                    "doctype": "Employee Checkin",
                    "employee": employee,
                    "time": rec.timestamp,
                    "device_id": self.device_id or None,
                })
                doc.insert(ignore_permissions=True)
                created += 1
            except Exception as exc:
                log_lines.append(f"{rec.user_id} @ {rec.timestamp}: {exc}")

        if unmapped_ids:
            log_lines.append(
                _("Unmapped device user ids: {0}").format(", ".join(sorted(unmapped_ids)))
            )

        self.total_records = total
        self.created_checkins = created
        self.created_employees = created_emps
        self.skipped_duplicates = duplicates
        self.skipped_unmapped = unmapped
        self.log = "\n".join(log_lines) or None
        self.status = "Imported" if created > 0 or total == 0 else "Failed"
        self.save(ignore_permissions=True)
        frappe.db.commit()

        return {
            "total": total,
            "created": created,
            "created_employees": created_emps,
            "duplicates": duplicates,
            "unmapped": unmapped,
        }


def _build_device_id_map() -> dict[str, str]:
    rows = frappe.get_all(
        "Employee",
        filters={"attendance_device_id": ["is", "set"]},
        fields=["name", "attendance_device_id"],
    )
    return {str(r["attendance_device_id"]).strip(): r["name"] for r in rows if r["attendance_device_id"]}


def _checkin_exists(employee: str, ts) -> bool:
    return bool(frappe.db.exists("Employee Checkin", {"employee": employee, "time": ts}))


def _create_placeholder_employee(device_user_id: str, company: str) -> str:
    """为尚未登记的设备 user_id 建一个占位员工，姓名填"未知"，打卡设备号填回去"""
    default_shift = frappe.db.get_single_value("Hourly Payroll Settings", "linked_shift_type")
    emp = frappe.get_doc({
        "doctype": "Employee",
        "first_name": PLACEHOLDER_FIRST_NAME,
        "employee_name": f"{PLACEHOLDER_FIRST_NAME} {device_user_id}",
        "attendance_device_id": device_user_id,
        "gender": "Other",
        "date_of_birth": PLACEHOLDER_DOB,
        "date_of_joining": today(),
        "company": company,
        "status": "Active",
        "default_shift": default_shift or None,
    })
    emp.flags.ignore_mandatory = True
    emp.insert(ignore_permissions=True)
    return emp.name
