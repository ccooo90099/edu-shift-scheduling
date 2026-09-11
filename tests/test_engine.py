"""引擎的时段运算 —— 本项目的空隙很不均匀，这几条最容易写错。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.slots import make_gap_counter, overlaps, parse_slot   # noqa: E402

SLOTS = ["08:10-10:10", "10:30-12:30", "13:30-15:30",
         "14:00-16:00", "16:20-18:20", "18:30-20:30"]


def test_解析时段():
    assert parse_slot("08:10-10:10") == (490, 610)


def test_重叠判定():
    assert overlaps(parse_slot("13:30-15:30"), parse_slot("14:00-16:00"))
    assert not overlaps(parse_slot("08:10-10:10"), parse_slot("10:30-12:30"))
    assert not overlaps(parse_slot("10:10-12:00"), parse_slot("12:00-14:00"))


def test_首尾相接的两节中间塞不下别的课():
    gap = make_gap_counter(SLOTS)
    assert gap(parse_slot("08:10-10:10"), parse_slot("10:30-12:30")) == 0


def test_跨午休也算中间没夹课():
    # 12:30→14:00 空 90 分钟，但中间排不下任何一个时段
    gap = make_gap_counter(SLOTS)
    assert gap(parse_slot("10:30-12:30"), parse_slot("14:00-16:00")) == 0


def test_中间夹了一节课就不算挨着():
    gap = make_gap_counter(SLOTS)
    assert gap(parse_slot("08:10-10:10"), parse_slot("14:00-16:00")) == 1


def test_午休是唯一来得及跨中心的窗口():
    starts = {s: parse_slot(s) for s in SLOTS}
    def wait(a, b):
        return starts[b][0] - starts[a][1]
    assert wait("08:10-10:10", "10:30-12:30") == 20
    assert wait("10:30-12:30", "14:00-16:00") == 90
    assert wait("14:00-16:00", "16:20-18:20") == 20
    assert wait("16:20-18:20", "18:30-20:30") == 10


# ── "挨着"的间隔阈值自动推算 ────────────────────────────────────
from engine.slots import adjacency_waits, derive_adjacency_limit   # noqa: E402


def test_列出所有相接组合的等待时长():
    assert adjacency_waits(SLOTS) == [10, 20, 50, 60, 90]


def test_自动推算把课间和午休分开():
    """教培不是托管，午休家长接走 —— 跨午休不能算"挨着"。"""
    limit, waits, why = derive_adjacency_limit(SLOTS)
    assert limit == 20
    assert "2.5 倍" in why
    # 课间算挨着
    assert all(w <= limit for w in (10, 20))
    # 午休那档不算
    assert all(w > limit for w in (50, 60, 90))


def test_时段表变了阈值跟着变():
    """改时段不用记得回来改死数。"""
    紧凑 = ["09:00-10:00", "10:10-11:10", "11:20-12:20", "14:00-15:00"]
    limit, _, _ = derive_adjacency_limit(紧凑)
    assert limit == 10            # 课间 10 分钟，午休 100 分钟被排除


def test_只有两个时段时也能推():
    limit, waits, _ = derive_adjacency_limit(["09:00-10:00", "10:20-11:20"])
    assert waits == [20] and limit == 20


def test_单个时段推不出跳变但不报错():
    limit, waits, why = derive_adjacency_limit(["09:00-10:00"])
    assert limit is None and waits == [] and "推不出" in why


# ── 两个被重叠时段揪出来的 bug ──────────────────────────────────

def test_区域不明时按跨区域算_兜底要保守():
    """两个 None 相等就当"同区域"的话，缺数据反而放宽约束。"""
    from engine.travel import Travel
    cfg = {"地理": {"判定方式": "时间", "时间": {"安全余量_分钟": 0}}}
    campus = {"甲": "甲", "乙": "乙"}
    t = Travel(cfg, {}, {}, campus, {})            # region_of 是空的
    assert t.tier("甲", "乙") == "跨区域"
    assert t.minutes("甲", "乙") == 70             # 不是同区域的 40

    有区域 = Travel(cfg, {}, {}, campus, {"甲": "福田", "乙": "福田"})
    assert 有区域.tier("甲", "乙") == "同区域"


def test_同校区判定不受空值影响():
    from engine.travel import Travel
    cfg = {"地理": {}}
    t = Travel(cfg, {}, {}, {}, {})                # campus_of 也是空的
    assert t.tier("甲", "乙") == "跨区域"          # 不是"同校区"
