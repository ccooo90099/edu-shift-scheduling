"""时段与时段表 —— 领域层最基础的值对象。"""
import pytest

from scheduling.domain.model.timeslot import TimeSlot
from scheduling.domain.model.timetable import Timetable

生产时段表 = ["08:10-10:10", "10:30-12:30", "14:00-16:00", "16:20-18:20", "18:30-20:30"]


def test_解析与回写是同一个字符串():
    assert TimeSlot.parse("08:10-10:10").text == "08:10-10:10"
    assert TimeSlot.parse("08:10-10:10") == TimeSlot(490, 610)


def test_结束早于开始直接拒绝而不是静默接受():
    with pytest.raises(ValueError, match="晚于"):
        TimeSlot(600, 500)
    with pytest.raises(ValueError):
        TimeSlot.parse("22:00-01:00")     # 跨夜时段目前不支持，宁可报错


def test_半开区间_端点相接不算重叠():
    a, b = TimeSlot.parse("08:00-10:00"), TimeSlot.parse("10:00-12:00")
    assert not a.overlaps(b) and not b.overlaps(a)
    assert a.is_before(b)
    assert a.gap_to(b) == 0


def test_重叠判定是对称的():
    """时段表里真的存在重叠档（13:30-15:30 × 14:00-16:00），
    单向判定会漏掉反向的一半。"""
    a, b = TimeSlot.parse("13:30-15:30"), TimeSlot.parse("14:00-16:00")
    assert a.overlaps(b)
    assert b.overlaps(a)


def test_从时段表自动推出课间阈值是20分钟():
    """现行五档表的相接间隔是 10/20/90，20→90 是最大跳变，
    所以 10/20 算课间、90（午休）算休息。"""
    t = Timetable(生产时段表)
    th = t.adjacency_threshold
    assert th.limit_minutes == 20
    assert th.observed_waits == (10, 20, 90)


def test_加回13点半那档也仍推出20分钟():
    """时段表可配置。加回重叠档后间隔变成 10/20/50/60/90，
    跳变点从 20→90 变成 20→50，阈值不变 —— 推导规则本身是稳的。"""
    th = Timetable(生产时段表 + ["13:30-15:30"]).adjacency_threshold
    assert th.limit_minutes == 20
    assert th.observed_waits == (10, 20, 50, 60, 90)


def test_并发组覆盖重叠_相接_与三重包含():
    assert Timetable(["08:10-10:10", "10:30-12:30"]).concurrent_groups == (
        (TimeSlot.parse("08:10-10:10"),), (TimeSlot.parse("10:30-12:30"),))

    重叠 = Timetable(["13:30-15:30", "14:00-16:00"]).concurrent_groups
    assert len(重叠[-1]) == 2, "重叠的两档必须出现在同一个并发组里"

    相接 = Timetable(["08:00-10:00", "10:00-12:00"]).concurrent_groups
    assert all(len(g) == 1 for g in 相接), "端点相接可以复用教室"

    三重 = Timetable(["08:00-12:00", "09:00-11:00", "10:00-10:30"]).concurrent_groups
    assert max(len(g) for g in 三重) == 3, "三重及以上并发也要计入"


def test_只看开始时刻就够_任意时刻的活跃集合必是某个开始时刻的子集():
    """并发组只在开始时刻取样。这个断言证明取样没有漏掉任何时刻。"""
    t = Timetable(["08:00-12:00", "09:00-11:00", "10:00-10:30", "11:30-13:00"])
    groups = [set(g) for g in t.concurrent_groups]
    for minute in range(8 * 60, 13 * 60):
        active = {s for s in t if s.start <= minute < s.end}
        if active:
            assert any(active <= g for g in groups), f"{minute} 分时的活跃集合没被覆盖"
