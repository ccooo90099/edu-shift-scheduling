"""降级链 —— 排不下的时候往哪儿退。

这是用户强调的真实痛点：不是「怎么排得好」，而是「排不下怎么办」。

一撮学生要上 3–5 门课，但一个校区一天能给他们开的节数有限
（「这个校区周六可能只有两节」）。塞不下就往下退：

  ① 全部科目在**本期位**内，同半天连堂          最优
  ② 都在本期位内，但分散了                      次优
  ③ **挪一部分到另一个期位**                     可接受
  ④ 彻底排不上                                  最差

因为期位是两个场景共用的维度，「拆到周六+周日两天」和「推到第二期」
**是同一个动作**，不需要两套逻辑。

**「挪到另一个期位」不等于「排不上」。** 只有「排上/没排上」两态的模型，
会把挪期位当成失败，导致求解器过度让步。
"""
from __future__ import annotations

from enum import IntEnum


class Placement(IntEnum):
    """安排结果。数值即惩罚序，必须严格递增。"""
    SAME_PERIOD_ADJACENT = 0    # ① 本期位内，连堂
    SAME_PERIOD_SCATTERED = 1   # ② 本期位内，分散
    SPLIT_ACROSS_PERIODS = 2    # ③ 挪一部分到另一个期位
    UNPLACED = 3                # ④ 排不上

    @property
    def label(self) -> str:
        return {0: "本期位内连堂", 1: "本期位内分散",
                2: "拆到两个期位", 3: "排不上"}[int(self)]

    def describe(self, season) -> str:
        from ..model.period import Season
        if self is not Placement.SPLIT_ACROSS_PERIODS:
            return self.label
        return ("拆到第一期和第二期" if season is Season.寒暑假
                else "拆到周六和周日")
