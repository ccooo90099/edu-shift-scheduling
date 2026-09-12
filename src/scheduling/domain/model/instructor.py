"""指导员。

属性来自后台配置（支持批量改和单个改），不是从排班表里猜出来的。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .curriculum import Product
from .timeslot import TimeSlot


@dataclass
class Instructor:
    name: str
    #: 资质是硬门槛。106 人里 103 人只教一个产品。
    teachable: set[Product] = field(default_factory=set)
    #: 空 = 不限
    allowed_centers: set[str] = field(default_factory=set)
    unavailable_slots: set[TimeSlot] = field(default_factory=set)
    unavailable_weekdays: set[str] = field(default_factory=set)
    max_sessions_per_day: int = 4
    max_centers_per_day: int = 2
    #: 不可调整名单 —— 排班时其安排固定不动
    is_immutable: bool = False

    def can_teach(self, team) -> bool:
        if team.product not in self.teachable:
            return False
        return not self.allowed_centers or team.center in self.allowed_centers

    def is_available_at(self, slot: TimeSlot) -> bool:
        return slot not in self.unavailable_slots

    @property
    def is_configured(self) -> bool:
        """没配资质的指导员要在顶部告警条里列出来 ——
        缺配置不会报错，只会让约束静默落空。"""
        return bool(self.teachable)
