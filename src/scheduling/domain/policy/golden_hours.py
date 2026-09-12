"""黄金时段与促销班。

黄金时段**只看一天当中的时间**，不看星期几，两个场景用同一套定义。

促销班的限制是**条件性硬排除**，不是可被其他目标抵消的软罚分 ——
用户原话是「不允许则**不排**黄金时间段」。开关打开时只是不做这道过滤，
**不是**反过来奖励促销班去占黄金档。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..model.timeslot import TimeSlot

#: 默认：上午两档
DEFAULT_GOLDEN = ("08:10-10:10", "10:30-12:30")


@dataclass(frozen=True)
class GoldenHoursPolicy:
    golden: frozenset[TimeSlot] = field(
        default_factory=lambda: frozenset(TimeSlot.parse(t) for t in DEFAULT_GOLDEN))
    promotional_may_use_golden: bool = False

    def is_golden(self, slot: TimeSlot) -> bool:
        return slot in self.golden

    def candidate_slots(self, open_slots, is_promotional: bool):
        """候选时段 = 当天允许时段 − 黄金时段（禁止时）。

        **必须取交集**：黄金时段只按时间定义，不代表可以忽略当天开不开门。
        春秋季周五只开 18:30-20:30，那天无论开关如何都只有这一档。
        """
        slots = list(open_slots)
        if is_promotional and not self.promotional_may_use_golden:
            return [s for s in slots if not self.is_golden(s)]
        return slots
