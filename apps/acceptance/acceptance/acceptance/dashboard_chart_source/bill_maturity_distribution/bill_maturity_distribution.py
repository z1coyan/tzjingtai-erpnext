# 承兑汇票到期分布柱状图数据源

import frappe
from frappe.utils import today, add_days, getdate


# 持有中的票据状态
HELD_STATUSES = ["Received - Circulating", "Endorsement Pending", "Payment Pending"]

# IN 子句占位符
_STATUS_PH = ", ".join(["%s"] * len(HELD_STATUSES))


def get(filters=None):
    """返回承兑汇票到期分布柱状图数据"""
    now = getdate(today())
    d7 = add_days(now, 7)
    d30 = add_days(now, 30)
    d90 = add_days(now, 90)

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
        frappe._("Overdue"),
        frappe._("Within 7 Days"),
        frappe._("8-30 Days"),
        frappe._("31-90 Days"),
        frappe._("Over 90 Days"),
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
        "datasets": [{"name": frappe._("Bill Amount"), "values": values}],
        "type": "bar",
    }
