"""新求解器 —— 每条对应一个已登记缺陷的回归测试。"""
import pytest

from scheduling.domain.model.cohort import Cohort, CohortKey, EnrollmentCombination
from scheduling.domain.model.curriculum import Grade, Tier, product_of
from scheduling.domain.model.instructor import Instructor
from scheduling.domain.model.period import Period, Season
from scheduling.domain.model.team import Team
from scheduling.domain.model.timetable import Timetable
from scheduling.domain.model.venue import Center, Room
from scheduling.domain.service.scheduling_problem import SchedulingProblem
from scheduling.infrastructure.solver.cpsat import CpSatScheduler

数学, 语文, 物理 = product_of("编程理论"), product_of("文学美育"), product_of("躬行实践")
五档 = Timetable(["08:10-10:10", "10:30-12:30", "14:00-16:00",
                  "16:20-18:20", "18:30-20:30"])


def 中心(name="甲", rooms=3, region="福田"):
    return Center(name=name, campus=Center.campus_of(name), region=region,
                  rooms=[Room(name, "R%d" % i, 30) for i in range(rooms)])


def 团队(tid, product, grade=Grade.S8, center="甲", tier=Tier.LI, **kw):
    return Team(id=tid, center=center, campus=Center.campus_of(center),
                region="福田", grade=grade, product=product, tier=tier, **kw)


def 老师(name, *products, centers=None):
    return Instructor(name=name, teachable=set(products),
                      allowed_centers=set(centers or ()))


def 问题(teams, instructors, centers, timetables=None, cohorts=None, **kw):
    return SchedulingProblem(
        season=Season.寒暑假, teams=teams,
        instructors={i.name: i for i in instructors},
        centers={c.name: c for c in centers},
        timetables=timetables or {Period.A: 五档},
        cohorts=cohorts or {}, **kw)


def 求解(p, **kw):
    return CpSatScheduler(p, time_limit=kw.pop("time_limit", 10),
                          workers=1, **kw).solve()


# ---------------------------------------------------------------- 基本可行

def test_两个班两个老师能全部排上():
    p = 问题([团队("T1", 数学), 团队("T2", 语文)],
             [老师("A", 数学), 老师("B", 语文)], [中心()])
    r = 求解(p)
    assert r.all_placed
    assert r.status in ("OPTIMAL", "FEASIBLE")


def test_没有合格老师的团队排不上而不是硬崩():
    p = 问题([团队("T1", 数学)], [老师("A", 语文)], [中心()])
    r = 求解(p)
    assert not r.all_placed


def test_S7不能开物理():
    """H5 年级 → 可开产品。"""
    p = 问题([团队("T1", 物理, grade=Grade.S7)], [老师("A", 物理)], [中心()])
    assert not 求解(p).all_placed


# ---------------------------------------------------------------- R10 教室重叠

def test_R10_教室容量按真实时间重叠算而不是按时段标签():
    """1 间教室 + 两个时间重叠但标签不同的档，只能排下一个。"""
    重叠表 = Timetable(["13:30-15:30", "14:00-16:00"])
    p = 问题([团队("T1", 数学), 团队("T2", 语文)],
             [老师("A", 数学), 老师("B", 语文)],
             [中心(rooms=1)], timetables={Period.A: 重叠表})
    r = 求解(p)
    assert sum(1 for t in r.teams if t.is_scheduled) == 1


def test_端点相接可以复用同一间教室():
    相接 = Timetable(["08:00-10:00", "10:00-12:00"])
    p = 问题([团队("T1", 数学), 团队("T2", 语文)],
             [老师("A", 数学), 老师("B", 语文)],
             [中心(rooms=1)], timetables={Period.A: 相接})
    assert 求解(p).all_placed


def test_三重重叠也受限():
    三重 = Timetable(["08:00-12:00", "09:00-11:00", "10:00-10:30"])
    p = 问题([团队("T%d" % i, 数学) for i in range(3)],
             [老师("A%d" % i, 数学) for i in range(3)],
             [中心(rooms=2)], timetables={Period.A: 三重})
    r = 求解(p)
    assert sum(1 for t in r.teams if t.is_scheduled) <= 2


# ---------------------------------------------------------------- H1 老师

def test_H1_同一老师不能同时带两个时间重叠的班():
    重叠表 = Timetable(["13:30-15:30", "14:00-16:00"])
    p = 问题([团队("T1", 数学), 团队("T2", 数学)],
             [老师("A", 数学)], [中心(rooms=5)],
             timetables={Period.A: 重叠表})
    r = 求解(p)
    assert sum(1 for t in r.teams if t.is_scheduled) == 1


# ---------------------------------------------------------------- R7 H2 放软

def test_R7_同程度不同产品可以同时段_只要没人同时报这两科():
    """H2 已由硬约束降级为软约束 S8。教室和时段容量不够平铺时，
    必须允许同时段开两门课。"""
    单档 = Timetable(["08:10-10:10"])
    p = 问题([团队("T1", 数学), 团队("T2", 语文)],
             [老师("A", 数学), 老师("B", 语文)],
             [中心(rooms=2)], timetables={Period.A: 单档})
    r = 求解(p)
    assert r.all_placed, "H2 若仍是硬约束，这里会有一个排不上"


def test_R7_有人同报两科时并发要扣分():
    单档 = Timetable(["08:10-10:10"])
    key = CohortKey("甲", Grade.S8, Tier.LI)
    cohort = Cohort(key, [EnrollmentCombination(frozenset({数学, 语文}), 20)])
    p = 问题([团队("T1", 数学), 团队("T2", 语文)],
             [老师("A", 数学), 老师("B", 语文)],
             [中心(rooms=2)], timetables={Period.A: 单档},
             cohorts={key: cohort})
    r = 求解(p)
    assert r.all_placed, "扣分但仍可行 —— 软约束不是硬约束"
    assert r.score_breakdown.get("并发每受影响学生") == 20


# ---------------------------------------------------------------- R2/R3 连堂

def test_R2_同报两科的学生优先排成同半天连堂():
    key = CohortKey("甲", Grade.S8, Tier.LI)
    cohort = Cohort(key, [EnrollmentCombination(frozenset({数学, 语文}), 30)])
    p = 问题([团队("T1", 数学), 团队("T2", 语文)],
             [老师("A", 数学), 老师("B", 语文)],
             [中心(rooms=3)], cohorts={key: cohort})
    r = 求解(p)
    assert r.all_placed
    a, b = sorted((t for t in r.teams), key=lambda t: t.slot.start)
    assert 五档.slots_between(a.slot, b.slot) == 0, "应排成相接的两档"


# ---------------------------------------------------------------- 黄金时段

def test_促销班在开关关闭时不得占黄金档():
    p = 问题([团队("T1", 数学, is_promotional=True)],
             [老师("A", 数学)], [中心()])
    r = 求解(p)
    assert r.all_placed
    assert r.teams[0].slot.text not in ("08:10-10:10", "10:30-12:30")


def test_春秋季周五只开一档时促销班仍只能排那一档():
    """黄金过滤要与当天营业时段取交集，不能因为过滤就把人排没。"""
    周五 = Timetable(["18:30-20:30"])
    p = 问题([团队("T1", 数学, is_promotional=True)],
             [老师("A", 数学)], [中心()], timetables={Period.A: 周五})
    r = 求解(p)
    assert r.all_placed and r.teams[0].slot.text == "18:30-20:30"


# ---------------------------------------------------------------- 状态汇报

def test_求解状态如实汇报_FEASIBLE不等于OPTIMAL():
    p = 问题([团队("T1", 数学)], [老师("A", 数学)], [中心()])
    r = 求解(p)
    assert r.status in ("OPTIMAL", "FEASIBLE")
    if r.status == "FEASIBLE":
        assert any("未证明最优" in n for n in r.notes)
    assert r.best_bound is not None


# ---------------------------------------------------------------- 场地容量两层

def test_校区并发上限比教室数更严时生效():
    """两栋楼加起来 4 间教室，但校区只允许同时开 2 个班。"""
    单档 = Timetable(["08:10-10:10"])
    teams = [团队("T%d" % i, 数学, center="百花科学" if i < 2 else "百花文学")
             for i in range(4)]
    p = 问题(teams, [老师("A%d" % i, 数学) for i in range(4)],
             [中心("百花科学", rooms=2), 中心("百花文学", rooms=2)],
             timetables={Period.A: 单档})
    assert 求解(p).all_placed, "只按教室数的话 4 个班放得下"

    p2 = 问题(teams, [老师("A%d" % i, 数学) for i in range(4)],
              [中心("百花科学", rooms=2), 中心("百花文学", rooms=2)],
              timetables={Period.A: 单档}, campus_caps={"百花": 2})
    r = 求解(p2)
    assert sum(1 for t in r.teams if t.is_scheduled) == 2, "校区上限 2 更严"


def test_没配校区上限时不凭空造限制():
    单档 = Timetable(["08:10-10:10"])
    teams = [团队("T%d" % i, 数学) for i in range(3)]
    p = 问题(teams, [老师("A%d" % i, 数学) for i in range(3)],
             [中心(rooms=3)], timetables={Period.A: 单档})
    assert 求解(p).all_placed


def test_教室数比校区上限更严时按教室数():
    单档 = Timetable(["08:10-10:10"])
    teams = [团队("T%d" % i, 数学) for i in range(3)]
    p = 问题(teams, [老师("A%d" % i, 数学) for i in range(3)],
             [中心(rooms=1)], timetables={Period.A: 单档},
             campus_caps={"甲": 10})
    assert sum(1 for t in 求解(p).teams if t.is_scheduled) == 1
