"""团队 —— 一个班，排班的基本单位。"""
from __future__ import annotations

from dataclasses import dataclass

from .cohort import CohortKey
from .curriculum import Grade, Product, Tier
from .period import Period
from .timeslot import TimeSlot


@dataclass(frozen=True)
class ConflictKey:
    """同校区同年级 —— H2 降级后的软约束 S8 按这个粒度算并发代价。"""
    campus: str
    grade: Grade


@dataclass
class Team:
    """一个待排的团队。期位、时段、指导员、教室是决策变量，其余是给定条件。"""
    id: str
    center: str
    campus: str
    region: str
    grade: Grade
    product: Product
    tier: Tier
    name: str = ""
    is_promotional: bool = False
    headcount: int = 0

    # —— 决策结果（未排定时为 None）——
    period: Period | None = None
    slot: TimeSlot | None = None
    instructor: str | None = None
    room: str | None = None

    # —— 原排班，修复模式下用来算「改动了多少」——
    original_slot: TimeSlot | None = None
    original_instructor: str | None = None
    original_period: Period | None = None

    #: 锁定的团队不参与决策，直接固定成常量。
    #: 全局软罚分保证不了小改动 —— 罚分会被别的目标抵消，真正管用的是显式锁定。
    is_locked: bool = False

    @property
    def cohort_key(self) -> CohortKey:
        return CohortKey(self.campus, self.grade, self.tier)

    @property
    def conflict_key(self) -> ConflictKey:
        return ConflictKey(self.campus, self.grade)

    @property
    def is_scheduled(self) -> bool:
        return self.slot is not None and self.instructor is not None

    def is_valid_product(self) -> bool:
        """年级 → 可开产品，硬约束。S7 不该出现物理化学。"""
        return self.product.available_to(self.grade)
