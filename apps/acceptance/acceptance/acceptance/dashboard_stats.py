# 承兑汇票统计数据API
# 为工作区数值卡片和图表提供数据

import frappe
from frappe.utils import today, add_days, getdate


# 持有中的票据状态（未转让、未贴现、未结清）
HELD_STATUSES = ["Received - Circulating", "Endorsement Pending", "Payment Pending"]

# IN 子句占位符
_STATUS_PH = ", ".join(["%s"] * len(HELD_STATUSES))


def _held_unexpired_sum(extra_condition="", extra_params=None):
    """查询持有中且未到期票据的金额合计"""
    params = list(HELD_STATUSES) + [today()]
    if extra_params:
        params.extend(extra_params)
    result = frappe.db.sql(
        """
        SELECT COALESCE(SUM(bill_amount), 0) AS total
        FROM `tabBill of Exchange`
        WHERE docstatus = 1
          AND bill_status IN ({statuses})
          AND due_date >= %s
          {cond}
        """.format(statuses=_STATUS_PH, cond=extra_condition),
        params,
        as_dict=True,
    )
    return result[0].total if result else 0


@frappe.whitelist()
def get_total_unexpired_amount(filters=None):
    """未到期承兑汇票持有总额"""
    value = _held_unexpired_sum()
    return {
        "value": value,
        "fieldtype": "Currency",
        "route_options": {"bill_status": ["in", list(HELD_STATUSES)]},
        "route": ["query-report", "Bill of Exchange"],
    }


@frappe.whitelist()
def get_expiring_7days_amount(filters=None):
    """7天内到期承兑汇票总额"""
    value = _held_unexpired_sum(
        "AND due_date <= %s",
        [add_days(today(), 7)],
    )
    return {
        "value": value,
        "fieldtype": "Currency",
    }


@frappe.whitelist()
def get_expiring_30days_amount(filters=None):
    """一月内到期承兑汇票总额"""
    value = _held_unexpired_sum(
        "AND due_date <= %s",
        [add_days(today(), 30)],
    )
    return {
        "value": value,
        "fieldtype": "Currency",
    }


@frappe.whitelist()
def get_maturity_chart_data(chart_name=None, filters=None):
    """承兑汇票到期分布柱状图数据"""
    now = getdate(today())
    d7 = add_days(now, 7)
    d30 = add_days(now, 30)
    d90 = add_days(now, 90)

    # 查询各区间金额
    rows = frappe.db.sql(
        """
        SELECT
            CASE
                WHEN due_date < %s THEN 'overdue'
                WHEN due_date <= %s THEN 'd7'
                WHEN due_date <= %s THEN 'd30'
                WHEN due_date <= %s THEN 'd90'
                ELSE 'd90plus'
            END AS bucket,
            COALESCE(SUM(bill_amount), 0) AS total
        FROM `tabBill of Exchange`
        WHERE docstatus = 1
          AND bill_status IN ({statuses})
        GROUP BY bucket
        ORDER BY FIELD(bucket, 'overdue', 'd7', 'd30', 'd90', 'd90plus')
        """.format(statuses=_STATUS_PH),
        [now, d7, d30, d90] + HELD_STATUSES,
        as_dict=True,
    )

    bucket_map = {r.bucket: r.total for r in rows}

    labels = [
        _("Overdue"),
        _("Within 7 Days"),
        _("8-30 Days"),
        _("31-90 Days"),
        _("Over 90 Days"),
    ]
    values = [
        float(bucket_map.get("overdue", 0)),
        float(bucket_map.get("d7", 0)),
        float(bucket_map.get("d30", 0)),
        float(bucket_map.get("d90", 0)),
        float(bucket_map.get("d90plus", 0)),
    ]

    return {
        "labels": labels,
        "datasets": [{"name": _("Bill Amount"), "values": values}],
        "type": "bar",
    }


def _(msg):
    """翻译辅助，兼容直接调用"""
    return frappe._(msg)
