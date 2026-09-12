"""时段 —— 一天当中的一段钟点。

本项目的时段空隙极不均匀（20/90/20/10 分钟），所以一切判断按真实钟点走，
不按格子序号。这是整个领域里最基础的值对象。
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property


def _to_minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _to_text(minutes: int) -> str:
    return "%02d:%02d" % divmod(minutes, 60)


@dataclass(frozen=True, order=True)
class TimeSlot:
    """一个时段，如 08:10-10:10。

    半开区间 [开始, 结束)：首尾相接的两节课不算重叠，可以复用教室。
    """
    start: int          # 当天第几分钟
    end: int

    def __post_init__(self):
        if self.end <= self.start:
            raise ValueError("时段结束时间必须晚于开始时间：%s" % self)

    @classmethod
    def parse(cls, text: str) -> "TimeSlot":
        """'08:10-10:10' → TimeSlot(490, 610)"""
        a, b = text.split("-")
        return cls(_to_minutes(a.strip()), _to_minutes(b.strip()))

    @cached_property
    def text(self) -> str:
        return "%s-%s" % (_to_text(self.start), _to_text(self.end))

    def __str__(self) -> str:
        return self.text

    @property
    def duration(self) -> int:
        return self.end - self.start

    def overlaps(self, other: "TimeSlot") -> bool:
        """时间上是否重叠 —— 重叠就意味着学生或老师要分身。"""
        return self.start < other.end and other.start < self.end

    def is_before(self, other: "TimeSlot") -> bool:
        """完全在对方之前（不重叠）。"""
        return self.end <= other.start

    def gap_to(self, other: "TimeSlot") -> int:
        """到下一节课之间空多少分钟。重叠或顺序颠倒时无意义，返回负数。"""
        return other.start - self.end
