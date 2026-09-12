"""学年日历 —— 批次的真实起止日期。

批次就是寒假 / 暑假 / 春季 / 秋季，具体日期每年跟着学校放假时间走，
所以是配置项不是常量。

**没有日历就查不出跨批次的指导员撞车**：批次在日期上可能重叠且共用教师，
按 (段次, 周) 分组求解会让这类冲突完全不被检查。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .period import Period, Season


@dataclass(frozen=True)
class Batch:
    """一个批次。"""
    name: str
    season: Season
    start: date
    end: date
    #: 各期位实际上课的日期
    period_dates: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.end < self.start:
            raise ValueError("批次结束日期不能早于开始日期：%s" % self.name)

    def dates_of(self, period: Period) -> tuple[date, ...]:
        return tuple(sorted(self.period_dates.get(period, ())))

    def overlaps(self, other: "Batch") -> bool:
        """日期区间是否相交。

        ⚠️ 区间相交**不等于**实际授课日重叠 —— 判定跨批次撞车必须比对
        真实授课日，不能拿区间相交当结论。
        """
        return self.start <= other.end and other.start <= self.end


class AcademicCalendar:
    """一学年的全部批次。"""

    def __init__(self, batches=()):
        self._batches = list(batches)

    def __iter__(self):
        return iter(self._batches)

    def __len__(self):
        return len(self._batches)

    def add(self, batch: Batch) -> None:
        self._batches.append(batch)

    @property
    def is_empty(self) -> bool:
        return not self._batches

    def teaching_days(self, period: Period) -> set[date]:
        days: set[date] = set()
        for b in self._batches:
            days.update(b.dates_of(period))
        return days

    def overlapping_pairs(self) -> list[tuple[Batch, Batch]]:
        """日期区间相交的批次对 —— 只是**候选**，需真实授课日核查。"""
        out = []
        for i, a in enumerate(self._batches):
            for b in self._batches[i + 1:]:
                if a.overlaps(b):
                    out.append((a, b))
        return out
