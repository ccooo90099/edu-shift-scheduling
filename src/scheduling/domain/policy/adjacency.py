"""连堂策略 —— 学生视角：一撮学生的课要连着上。

三档偏好，从好到差：
  ① 同半天连排   8:10→10:30，或 14:00→16:20→18:30
  ② 跨午休连排   10:30→14:00，可接受，次优
  ③ 分散         中间隔着别的时段，能排上就行

**跨午休算连堂。** 这一条推翻过一次早期设计：曾把自动推出的 20 分钟
课间阈值当成硬门槛，等于把跨午休判为不连堂 —— 与业务定案相反。
阈值的正确用途是**区分①和②**，不是决定「算不算连堂」。

只看当天，不跨日。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from ..model.timeslot import TimeSlot
from ..model.timetable import Timetable


class AdjacencyGrade(IntEnum):
    """连堂达成度。数值即惩罚档位，越大越差。"""
    SAME_HALF_DAY = 0       # ① 同半天连排
    ACROSS_LUNCH = 1        # ② 跨午休连排
    SCATTERED = 2           # ③ 分散
    UNSCHEDULED = 3         # 有一节没排上

    @property
    def label(self) -> str:
        return {0: "同半天连排", 1: "跨午休连排",
                2: "分散", 3: "未排上"}[int(self)]


@dataclass(frozen=True)
class AdjacencyPolicy:
    """判定两节课的连堂档位。"""
    timetable: Timetable
    #: 小于等于它算课间（同半天）；None 表示从时段表自动推导
    break_limit_minutes: int | None = None

    @property
    def limit(self) -> int:
        if self.break_limit_minutes is not None:
            return self.break_limit_minutes
        derived = self.timetable.adjacency_threshold.limit_minutes
        return derived if derived is not None else 0

    def grade(self, a: TimeSlot | None, b: TimeSlot | None) -> AdjacencyGrade:
        if a is None or b is None:
            return AdjacencyGrade.UNSCHEDULED
        first, second = (a, b) if a.start <= b.start else (b, a)
        if not first.is_before(second):
            return AdjacencyGrade.SCATTERED      # 重叠 —— 学生没法同时上
        if self.timetable.slots_between(first, second) > 0:
            return AdjacencyGrade.SCATTERED      # 中间夹着别的课
        return (AdjacencyGrade.SAME_HALF_DAY
                if first.gap_to(second) <= self.limit
                else AdjacencyGrade.ACROSS_LUNCH)
