"""期位 —— 两个场景共用的同一个维度。

暑假第一期的课平移到春秋季的周六，第二期平移到周日。所以不需要
「期」和「星期」两个维度，一个期位变量就够；渲染成「第一期」还是
「周六」是输出层的事。
"""
from __future__ import annotations

from enum import Enum


class Season(Enum):
    """场景。两者排课逻辑相同，区别只在时段表和一个批次由哪些天组成。"""
    寒暑假 = "寒暑假"
    春秋季 = "春秋季"


class Period(Enum):
    """期位。A 优先于 B —— 用户原话「周六其实更好排」。"""
    A = "A"
    B = "B"

    def label(self, season: Season) -> str:
        if season is Season.寒暑假:
            return {"A": "第一期", "B": "第二期"}[self.value]
        return {"A": "周六", "B": "周日"}[self.value]

    @property
    def is_preferred(self) -> bool:
        return self is Period.A

    @property
    def other(self) -> "Period":
        return Period.B if self is Period.A else Period.A
