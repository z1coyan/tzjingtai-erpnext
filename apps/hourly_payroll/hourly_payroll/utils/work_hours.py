"""
工时算法：从 Employee Checkin 按配置的上午/下午/加班三段时间窗分别计算工时，
并填回 Attendance 的 regular_hours / overtime_hours / net_work_hours。

算法要点：
  - 三个时间窗（上午/下午/加班）按顺序排列且互不重叠
  - 每条打卡归属到"距离最近的一个窗"，并要求距离在容差内，避免相邻窗容差区重叠导致双算
  - 每个窗内最早-最晚打卡之差作为该段原始时长（少于两次打卡该段为 0）
  - 正班 = 上午段 + 下午段；加 extra_minutes 后按 round_unit_hours 向下截断，封顶 regular_cap_hours
  - 加班段若原始时长 + overtime_full_tolerance_minutes ≥ overtime_full_threshold_hours，
    直接按 overtime_full_credit_hours 计（全勤奖励）；否则同样 +extra_minutes → 向下截断
"""

from __future__ import annotations

from datetime import date as date_type, datetime, time, timedelta


def recalc_attendance_hours(doc, method=None):
    """Attendance before_save 钩子：重算三段工时"""
    import frappe
    from frappe.utils import getdate

    if not doc.employee or not doc.attendance_date:
        return

    settings = frappe.get_cached_doc("Hourly Payroll Settings")
    att_date = getdate(doc.attendance_date)
    checkins = _load_checkins(doc.employee, att_date)

    regular, overtime = compute_day_hours(checkins, att_date, settings)

    doc.regular_hours = regular
    doc.overtime_hours = overtime
    doc.net_work_hours = regular + overtime


def compute_day_hours(checkins: list[datetime], att_date: date_type, settings) -> tuple[float, float]:
    """
    给定一天的全部 checkin datetime 和当日日期，返回 (regular_hours, overtime_hours)。
    纯函数，便于单元测试。
    """
    if not checkins:
        return 0.0, 0.0

    buffer = timedelta(minutes=settings.window_buffer_minutes or 0)
    extra_secs = (settings.extra_minutes or 0) * 60
    unit = float(settings.round_unit_hours or 0.5)
    reg_cap = float(settings.regular_cap_hours or 8)

    windows = _build_windows(att_date, settings)
    buckets: list[list[datetime]] = [[] for _ in windows]
    for c in checkins:
        idx = _classify(c, windows, buffer)
        if idx is not None:
            buckets[idx].append(c)

    morning_secs = _span_seconds(buckets[0])
    afternoon_secs = _span_seconds(buckets[1])
    overtime_secs = _span_seconds(buckets[2]) if len(buckets) > 2 else 0.0

    regular_raw = morning_secs + afternoon_secs
    regular = _round_down(regular_raw + extra_secs, unit) if regular_raw > 0 else 0.0
    regular = min(regular, reg_cap)

    overtime = _apply_overtime_rule(overtime_secs, extra_secs, unit, settings)

    return regular, overtime


def _apply_overtime_rule(overtime_secs: float, extra_secs: float, unit: float, settings) -> float:
    if overtime_secs <= 0:
        return 0.0

    full_threshold = float(settings.overtime_full_threshold_hours or 0)
    full_credit = float(settings.overtime_full_credit_hours or 0)
    tol_secs = (settings.overtime_full_tolerance_minutes or 0) * 60

    if full_threshold > 0 and overtime_secs + tol_secs >= full_threshold * 3600:
        return full_credit

    return _round_down(overtime_secs + extra_secs, unit)


def _build_windows(att_date: date_type, settings) -> list[tuple[datetime, datetime]]:
    """返回按时间顺序、且已经去除重叠的 [(start, end), ...]"""
    raw = []
    if settings.morning_start and settings.morning_end:
        raw.append((_combine(att_date, settings.morning_start), _combine(att_date, settings.morning_end)))
    if settings.afternoon_start and settings.afternoon_end:
        raw.append((_combine(att_date, settings.afternoon_start), _combine(att_date, settings.afternoon_end)))
    if settings.overtime_start and settings.overtime_end:
        raw.append((_combine(att_date, settings.overtime_start), _combine(att_date, settings.overtime_end)))
    raw.sort(key=lambda w: w[0])
    return raw


def _classify(c: datetime, windows: list[tuple[datetime, datetime]], buffer: timedelta) -> int | None:
    """把打卡归到距离最近的窗口。距离超过 buffer 的丢弃。"""
    best_idx: int | None = None
    best_dist: float | None = None
    for i, (s, e) in enumerate(windows):
        if c < s:
            d = (s - c).total_seconds()
        elif c > e:
            d = (c - e).total_seconds()
        else:
            d = 0.0
        if best_dist is None or d < best_dist:
            best_dist = d
            best_idx = i
    if best_dist is None or best_dist > buffer.total_seconds():
        return None
    return best_idx


def _span_seconds(items: list[datetime]) -> float:
    if len(items) < 2:
        return 0.0
    return (max(items) - min(items)).total_seconds()


def _combine(d: date_type, val) -> datetime:
    return datetime.combine(d, _as_time(val))


def _as_time(val) -> time:
    """Settings 里的 Time 字段可能是 timedelta/str/time"""
    if isinstance(val, time):
        return val
    if isinstance(val, timedelta):
        total = int(val.total_seconds())
        return time(total // 3600, (total % 3600) // 60, total % 60)
    if isinstance(val, str):
        parts = val.split(":")
        return time(int(parts[0]), int(parts[1]) if len(parts) > 1 else 0, int(parts[2]) if len(parts) > 2 else 0)
    raise TypeError(f"Unsupported time value: {val!r}")


def _round_down(seconds: float, unit_hours: float) -> float:
    if unit_hours <= 0:
        return round(seconds / 3600, 2)
    unit_secs = unit_hours * 3600
    return (int(seconds // unit_secs)) * unit_hours


def _load_checkins(employee: str, att_date: date_type) -> list[datetime]:
    import frappe
    from frappe.utils import get_datetime

    rows = frappe.get_all(
        "Employee Checkin",
        filters={
            "employee": employee,
            "time": ["between", [f"{att_date} 00:00:00", f"{att_date} 23:59:59"]],
        },
        fields=["time"],
        order_by="time asc",
    )
    return [get_datetime(r["time"]) for r in rows]
