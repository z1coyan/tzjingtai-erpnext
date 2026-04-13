"""承兑持有台账 —— 区间合并 / 拆分算法。

核心约束（新一代电子承兑）：
- 每张主票号下持有若干个**不重叠**的子票区间；邻接区间自动合并。
- 区间金额 = (to - from + 1) / 100 —— 电子承兑最小单位是 0.01 元，每个子票号对应 1 分。
- 接收时：新区间合并进持有台账；校验不与已有段重叠。
- 转出 / 贴现 / 兑付时：目标区间必须完整落在某一段持有段内，从该段切走，可能产生 1-2 段剩余。

兼容老票（纸票 / 无子票号的老电票）：
- `is_legacy or not is_electronic` 分支，segments 子表每行只记 amount，整行接收 / 整行转出，不做区间合并。
"""

from __future__ import annotations

from decimal import Decimal

import frappe
from frappe import _
from frappe.utils import flt


SEGMENT_STATUS_HELD = "Held"

SUB_DRAFT_PAD = 8  # 电子承兑子票号统一按 8 位零填充显示


# ---------- 底层整数区间算法 ----------


def _to_int(val) -> int:
    if val is None or val == "":
        frappe.throw(_("Sub-bill number cannot be empty"))
    try:
        return int(str(val).strip())
    except ValueError:
        frappe.throw(_("Sub-bill number {0} is not a valid integer").format(val))


def _pad(n: int) -> str:
    return str(n).zfill(SUB_DRAFT_PAD)


def amount_from_range(from_val, to_val) -> float:
    """(to - from + 1) / 100，用 Decimal 保 2 位精度。"""
    f = _to_int(from_val)
    t = _to_int(to_val)
    if t < f:
        frappe.throw(_("Segment To ({0}) must be >= Segment From ({1})").format(t, f))
    return flt(Decimal(t - f + 1) / Decimal(100), 2)


def validate_range_and_amount(from_val, to_val, amount) -> None:
    expected = amount_from_range(from_val, to_val)
    if abs(flt(amount) - expected) > 0.001:
        frappe.throw(
            _("Amount {0} does not match sub-bill range {1}-{2}; expected {3}").format(
                flt(amount), from_val, to_val, expected
            )
        )


def merge_intervals(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if not intervals:
        return []
    sorted_iv = sorted(intervals)
    merged: list[list[int]] = [list(sorted_iv[0])]
    for s, e in sorted_iv[1:]:
        last = merged[-1]
        if s <= last[1] + 1:
            last[1] = max(last[1], e)
        else:
            merged.append([s, e])
    return [(s, e) for s, e in merged]


def assert_no_overlap(holdings: list[tuple[int, int]], new_from: int, new_to: int) -> None:
    for s, e in holdings:
        if not (new_to < s or new_from > e):
            frappe.throw(
                _("New range {0}-{1} overlaps with existing held segment {2}-{3}").format(
                    _pad(new_from), _pad(new_to), _pad(s), _pad(e)
                )
            )


def subtract_interval(
    holdings: list[tuple[int, int]], r_from: int, r_to: int
) -> list[tuple[int, int]]:
    """从持有区间列表里切掉 [r_from, r_to]，要求完整落在某一段内。"""
    new: list[tuple[int, int]] = []
    found = False
    for s, e in holdings:
        if r_to < s or r_from > e:
            new.append((s, e))
            continue
        if r_from < s or r_to > e:
            frappe.throw(
                _("Target range {0}-{1} is not fully contained in a single held segment").format(
                    _pad(r_from), _pad(r_to)
                )
            )
        found = True
        if s < r_from:
            new.append((s, r_from - 1))
        if r_to < e:
            new.append((r_to + 1, e))
    if not found:
        frappe.throw(
            _("No held segment contains range {0}-{1}").format(_pad(r_from), _pad(r_to))
        )
    return new


# ---------- Bill of Exchange 台账操作（电子票分支） ----------


def get_current_holdings(bill_doc) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for row in bill_doc.segments:
        if not row.segment_from or not row.segment_to:
            continue
        out.append((_to_int(row.segment_from), _to_int(row.segment_to)))
    return out


def rebuild_holdings(bill_doc, holdings: list[tuple[int, int]]) -> None:
    """把 bill.segments 全量重建为给定的持有段列表。"""
    bill_doc.set("segments", [])
    for s, e in holdings:
        bill_doc.append(
            "segments",
            {
                "segment_from": _pad(s),
                "segment_to": _pad(e),
                "amount": amount_from_range(s, e),
                "status": SEGMENT_STATUS_HELD,
                "holder_type": "Self",
            },
        )


def add_electronic_range(bill_doc, new_from, new_to) -> None:
    r_f = _to_int(new_from)
    r_t = _to_int(new_to)
    current = get_current_holdings(bill_doc)
    assert_no_overlap(current, r_f, r_t)
    merged = merge_intervals(current + [(r_f, r_t)])
    rebuild_holdings(bill_doc, merged)


def remove_electronic_range(bill_doc, from_val, to_val) -> None:
    r_f = _to_int(from_val)
    r_t = _to_int(to_val)
    current = get_current_holdings(bill_doc)
    new = subtract_interval(current, r_f, r_t)
    rebuild_holdings(bill_doc, new)


# ---------- 老票分支（按金额行处理，不做区间合并） ----------


def add_legacy_row(bill_doc, amount) -> None:
    bill_doc.append(
        "segments",
        {
            "amount": flt(amount),
            "status": SEGMENT_STATUS_HELD,
            "holder_type": "Self",
        },
    )


def remove_legacy_row(bill_doc, amount) -> None:
    target = flt(amount)
    for row in list(bill_doc.segments):
        if abs(flt(row.amount) - target) < 0.001:
            bill_doc.remove(row)
            return
    frappe.throw(_("No legacy held segment with amount {0} found").format(target))


# ---------- 共用 ----------


def is_legacy_bill(bill_doc) -> bool:
    return bool(bill_doc.is_legacy) or not bool(bill_doc.is_electronic)


def recompute_bill_status(bill_doc) -> None:
    total_held = sum(flt(r.amount or 0) for r in bill_doc.segments)
    bill_doc.outstanding_amount = total_held
    face = flt(bill_doc.face_amount or 0)
    if total_held <= 0:
        bill_doc.status = "Fully Settled"
    elif face > 0 and total_held < face:
        bill_doc.status = "Partially Settled"
    else:
        bill_doc.status = "Active"
