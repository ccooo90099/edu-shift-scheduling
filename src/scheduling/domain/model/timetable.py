"""时段表 —— 一天开哪几档课。

它不只是一个列表：课间与休息的分界线是**从时段表本身推出来的**，
换一套时段表不用重新填参数。
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

from .timeslot import TimeSlot


@dataclass(frozen=True)
class AdjacencyThreshold:
    """课间与休息的分界。"""
    limit_minutes: int | None       # 小于等于它算课间；None 表示推不出来
    observed_waits: tuple[int, ...]
    explanation: str


class Timetable:
    """一天的时段表。不可变。"""

    def __init__(self, slots):
        parsed = [s if isinstance(s, TimeSlot) else TimeSlot.parse(s) for s in slots]
        if not parsed:
            raise ValueError("时段表不能为空")
        self._slots = tuple(sorted(set(parsed)))

    def __iter__(self):
        return iter(self._slots)

    def __len__(self):
        return len(self._slots)

    def __contains__(self, slot):
        return slot in self._slots

    @property
    def slots(self) -> tuple[TimeSlot, ...]:
        return self._slots

    @cached_property
    def texts(self) -> tuple[str, ...]:
        return tuple(s.text for s in self._slots)

    def slots_between(self, a: TimeSlot, b: TimeSlot) -> int:
        """a 结束到 b 开始之间，还塞得下几个别的时段。

        0 表示两节课首尾相接（中间没有别的课），这才叫「挨着」。
        """
        return sum(1 for s in self._slots if a.end <= s.start and s.end <= b.start)

    @cached_property
    def concurrent_groups(self) -> tuple[tuple[TimeSlot, ...], ...]:
        """所有可能同时进行的时段组合，供教室容量约束用。

        重叠集合只在课程开始或结束时变化，而任意时刻 t 的活跃集合必是
        「t 之前最后一个开始时刻」的活跃集合的子集 —— 所以只看开始时刻就够。
        """
        groups, seen = [], set()
        for instant in sorted({s.start for s in self._slots}):
            group = tuple(s for s in self._slots if s.start <= instant < s.end)
            if group not in seen:
                groups.append(group)
                seen.add(group)
        return tuple(groups)

    @cached_property
    def adjacency_waits(self) -> tuple[int, ...]:
        """所有「中间夹不下别的课」的相接组合，学生各要等多久。"""
        waits = set()
        for i, a in enumerate(self._slots):
            for b in self._slots[i + 1:]:
                if not a.is_before(b):
                    continue
                if self.slots_between(a, b) == 0:
                    waits.add(a.gap_to(b))
        return tuple(sorted(waits))

    @cached_property
    def adjacency_threshold(self) -> AdjacencyThreshold:
        """从时段表推算课间与休息的分界。

        把相接间隔排序，找最大的一次**比值跳变**：跳变以下是课间，以上是
        午休那种真正的休息。当前时段表推出 20 分钟（20→50 是 2.5 倍）。
        """
        waits = [w for w in self.adjacency_waits if w > 0]
        if len(waits) < 2:
            return AdjacencyThreshold(waits[0] if waits else None,
                                      tuple(waits), "时段太少，推不出跳变")
        ratio, index = max((waits[i + 1] / waits[i], i) for i in range(len(waits) - 1))
        limit = waits[index]
        return AdjacencyThreshold(
            limit, tuple(waits),
            "%d → %d 分钟是最大跳变（%.1f 倍）：%s 算课间，%s 算休息" % (
                limit, waits[index + 1], ratio,
                "/".join(str(w) for w in waits if w <= limit),
                "/".join(str(w) for w in waits if w > limit)))

    def __repr__(self):
        return "Timetable(%s)" % ", ".join(self.texts)
