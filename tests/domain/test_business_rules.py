"""业务规则的领域层测试。

这里每一条都对应一次真实的口径纠正，注释里写明「当初错在哪」，
免得后来的人把它改回去。
"""
import pytest

from scheduling.domain.model.cohort import (
    Cohort, CohortKey, EnrollmentCombination)
from scheduling.domain.model.curriculum import Grade, Tier, product_of
from scheduling.domain.model.period import Period, Season
from scheduling.domain.model.timeslot import TimeSlot
from scheduling.domain.model.timetable import Timetable
from scheduling.domain.policy.adjacency import AdjacencyGrade, AdjacencyPolicy
from scheduling.domain.policy.degradation import Placement
from scheduling.domain.policy.golden_hours import GoldenHoursPolicy
from scheduling.domain.policy.travel import (
    ProximityTier, count_transfers, proximity_tier)
from scheduling.domain.policy.weights import DEFAULT_WEIGHTS, Weights

五档 = Timetable(["08:10-10:10", "10:30-12:30", "14:00-16:00",
                  "16:20-18:20", "18:30-20:30"])
数学, 语文, 英语 = product_of("编程理论"), product_of("文学美育"), product_of("双语文化")
物理 = product_of("躬行实践")


# ---------------------------------------------------------------- 连堂三档

def test_连堂三档_跨午休算连堂而不是不连堂():
    """曾经把自动推出的 20 分钟当成硬门槛，等于把跨午休判为不连堂 ——
    与业务定案相反。用户原话：「跨午休到底也算连」。"""
    p = AdjacencyPolicy(五档)
    上午连排 = p.grade(TimeSlot.parse("08:10-10:10"), TimeSlot.parse("10:30-12:30"))
    跨午休 = p.grade(TimeSlot.parse("10:30-12:30"), TimeSlot.parse("14:00-16:00"))
    分散 = p.grade(TimeSlot.parse("08:10-10:10"), TimeSlot.parse("14:00-16:00"))

    assert 上午连排 is AdjacencyGrade.SAME_HALF_DAY
    assert 跨午休 is AdjacencyGrade.ACROSS_LUNCH
    assert 分散 is AdjacencyGrade.SCATTERED
    assert 上午连排 < 跨午休 < 分散, "三档的惩罚必须严格递增"


def test_连堂判定与顺序无关():
    p = AdjacencyPolicy(五档)
    a, b = TimeSlot.parse("08:10-10:10"), TimeSlot.parse("10:30-12:30")
    assert p.grade(a, b) is p.grade(b, a)


def test_没排上的课单独一档而不是混进分散():
    assert AdjacencyPolicy(五档).grade(TimeSlot.parse("08:10-10:10"), None) \
        is AdjacencyGrade.UNSCHEDULED


# ---------------------------------------------------------------- 报读组合

def test_人群不等于全科_只报两科的学生不该被要求排五门():
    """Q21：曾经用年级推出「S9 该上五门」，等于把已降级的 H2 从后门放回来。"""
    c = Cohort(CohortKey("百花", Grade.S9, Tier.LI), [
        EnrollmentCombination(frozenset({数学, 物理}), 18),
        EnrollmentCombination(frozenset({数学}), 6),
    ])
    assert len(c.available_products) == 5, "年级能开五门"
    assert all(len(x.products) <= 2 for x in c.combinations), "但没人报五门"
    assert c.total_headcount == 24


def test_并发代价按同报人数算而不是按存在并发产品对算():
    """H2 降级为 S8 之后，代价正比于**同时报了这两科的人数**，
    不是「存在两个不同产品并发」这个事实本身。"""
    c = Cohort(CohortKey("百花", Grade.S8, Tier.LI), [
        EnrollmentCombination(frozenset({数学, 物理}), 18),
        EnrollmentCombination(frozenset({数学, 语文}), 22),
        EnrollmentCombination(frozenset({英语}), 5),
    ])
    assert c.headcount_taking_both(数学, 物理) == 18
    assert c.headcount_taking_both(数学, 语文) == 22
    assert c.headcount_taking_both(语文, 物理) == 0, "没人同时报这两科，撞了也不伤人"


def test_配对优先级由实际人数决定而不是固定顺序():
    """默认序是 数学+语文 > 数学+英语 > 语文+英语，但某校区数学+物理的人
    特别多时，优先级就该变 —— 它是数据驱动的。"""
    c = Cohort(CohortKey("石厦", Grade.S8, Tier.LE), [
        EnrollmentCombination(frozenset({数学, 物理}), 40),
        EnrollmentCombination(frozenset({数学, 语文}), 12),
    ])
    top = max(c.pair_weights().items(), key=lambda kv: kv[1])[0]
    assert top == frozenset({数学, 物理})


def test_空组合直接拒绝():
    with pytest.raises(ValueError):
        EnrollmentCombination(frozenset(), 10)


# ---------------------------------------------------------------- 转场

def test_转场按实际中心变更计_ABA是两次不是一次():
    """R4：求解曾算 distinct−1、体检算实际事件，同一份排班报出 19 和 25。"""
    assert count_transfers(["甲", "乙", "甲"]) == 2
    assert count_transfers(["甲", "甲", "乙", "甲"]) == 2
    assert count_transfers(["甲", "甲", "甲"]) == 0
    assert count_transfers([]) == 0


def test_区域不明时兜底按跨区域算而不是同区域():
    """曾经传空的 region_of，None == None 让全部中心读成同区域
    （40 分钟而不是 70），把不可能的转场判成可行。兜底必须保守。"""
    campus = {"百花科学": "百花", "百花文学": "百花"}
    assert proximity_tier("百花科学", "百花文学", campus, {}) is ProximityTier.SAME_CAMPUS
    assert proximity_tier("甲", "乙", {}, {}) is ProximityTier.CROSS_REGION
    assert proximity_tier("甲", "乙", {}, {"甲": "福田"}) is ProximityTier.CROSS_REGION
    assert proximity_tier("甲", "乙", {}, {"甲": "福田", "乙": "福田"}) \
        is ProximityTier.SAME_REGION


# ---------------------------------------------------------------- 黄金时段

def test_促销班候选时段要与当天开门时段取交集():
    """曾经写「关掉开关时两个场景一致，都可排下午晚上三档」，
    漏了春秋季周五本来就只开 18:30 这一档。"""
    p = GoldenHoursPolicy()
    周末全开 = [TimeSlot.parse(t) for t in
                ["08:10-10:10", "10:30-12:30", "14:00-16:00",
                 "16:20-18:20", "18:30-20:30"]]
    周五仅一档 = [TimeSlot.parse("18:30-20:30")]

    assert len(p.candidate_slots(周末全开, is_promotional=True)) == 3
    assert p.candidate_slots(周五仅一档, is_promotional=True) == 周五仅一档
    assert len(p.candidate_slots(周末全开, is_promotional=False)) == 5


def test_开关打开只是不过滤而不是奖励促销班():
    p = GoldenHoursPolicy(promotional_may_use_golden=True)
    全部 = [TimeSlot.parse(t) for t in ["08:10-10:10", "14:00-16:00"]]
    assert p.candidate_slots(全部, True) == p.candidate_slots(全部, False)


# ---------------------------------------------------------------- 期位与降级

def test_一个期位变量同时表达两个场景():
    assert Period.A.label(Season.寒暑假) == "第一期"
    assert Period.A.label(Season.春秋季) == "周六"
    assert Period.A.is_preferred and not Period.B.is_preferred
    assert Period.A.other is Period.B


def test_挪期位不等于排不上():
    """只有两态的模型会把挪期位当失败，导致求解器过度让步。"""
    assert Placement.SPLIT_ACROSS_PERIODS < Placement.UNPLACED
    assert (Placement.SAME_PERIOD_ADJACENT < Placement.SAME_PERIOD_SCATTERED
            < Placement.SPLIT_ACROSS_PERIODS < Placement.UNPLACED)
    assert Placement.SPLIT_ACROSS_PERIODS.describe(Season.寒暑假) == "拆到第一期和第二期"
    assert Placement.SPLIT_ACROSS_PERIODS.describe(Season.春秋季) == "拆到周六和周日"


# ---------------------------------------------------------------- 权重

def test_权重是按键覆盖_未提供的键保留默认():
    """曾把机制说成「整块覆盖」。实际是 dict() 后 update()。"""
    w = Weights.from_config({"转场一次": 800})
    assert w["转场一次"] == 800
    assert w["连堂未达标"] == DEFAULT_WEIGHTS["连堂未达标"]


def test_未知权重键直接报错而不是静默忽略():
    """改键名没同步到体检侧，一侧会静默用默认值 —— 宁可启动就炸。"""
    with pytest.raises(ValueError, match="未知权重键"):
        Weights.from_config({"工作量方差": 30})


def test_生效权重报告标出被覆盖的项():
    """曾连续三轮调权重完全不生效，因为配置文件里还是旧值。"""
    report = Weights.from_config({"转场一次": 800}).effective_report()
    assert "★ 转场一次" in report
    assert "  连堂未达标" in report


def test_降级链的权重序必须严格递减():
    w = Weights()
    assert w["排不上团队"] > w["挪到另一期位"] > w["期位与历史不符"] > w["连堂未达标"]


# ---------------------------------------------------------------- 教室数可配

def test_教室数可以直接填_实数覆盖估计值():
    """校区的教室是有限且已知的（5 间、6 间这种），
    不该只能靠从历史并发峰值推。后台填的实数比推出来的可信。"""
    from scheduling.domain.model.venue import Center, Room
    c = Center("甲", "甲", rooms=[Room("甲", "估1"), Room("甲", "估2")],
               rooms_are_estimated=True)
    c.set_room_count(6, estimated=False)
    assert c.room_count == 6
    assert not c.rooms_are_estimated, "人填的不再是估计"


def test_改教室数时保留已有教室的座位与不可用时段():
    """多退少补，不要把已经配好的教室信息冲掉。"""
    from scheduling.domain.model.venue import Center, Room
    from scheduling.domain.model.timeslot import TimeSlot
    早上 = TimeSlot.parse("08:10-10:10")
    c = Center("甲", "甲", rooms=[Room("甲", "01", 24, frozenset({早上}))])
    c.set_room_count(3)
    assert c.room_count == 3
    assert c.rooms[0].seats == 24 and 早上 in c.rooms[0].unavailable
    c.set_room_count(1)
    assert c.room_count == 1 and c.rooms[0].room_id == "01"


def test_教室数不能为负():
    from scheduling.domain.model.venue import Center
    import pytest as _p
    with _p.raises(ValueError):
        Center("甲", "甲").set_room_count(-1)
