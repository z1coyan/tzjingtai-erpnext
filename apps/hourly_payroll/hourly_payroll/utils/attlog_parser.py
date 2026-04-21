"""
ZKTeco attlog.dat 解析。

格式（tab 分隔，CRLF）：
    user_id \t YYYY-MM-DD HH:MM:SS \t status \t verify \t workcode \t reserved

user_id 可能带前导空格（右对齐）。同一 user_id 同一秒可能出现多条，去重。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Iterator


@dataclass(frozen=True)
class AttLogRecord:
    user_id: str
    timestamp: datetime


def parse_attlog(text: str) -> list[AttLogRecord]:
    seen: set[tuple[str, datetime]] = set()
    out: list[AttLogRecord] = []
    for rec in _iter_records(text.splitlines()):
        key = (rec.user_id, rec.timestamp)
        if key in seen:
            continue
        seen.add(key)
        out.append(rec)
    out.sort(key=lambda r: (r.user_id, r.timestamp))
    return out


def _iter_records(lines: Iterable[str]) -> Iterator[AttLogRecord]:
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        user_id = parts[0].strip()
        ts_str = parts[1].strip()
        if not user_id or not ts_str:
            continue
        try:
            ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        yield AttLogRecord(user_id=user_id, timestamp=ts)
