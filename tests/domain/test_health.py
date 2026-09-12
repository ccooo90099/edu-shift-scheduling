"""体检 —— R1 与「未检查项必须显式列出」的回归。"""
from datetime import date

from scheduling.domain.model.academic_calendar import AcademicCalendar, Batch
from scheduling.domain.model.curriculum import Grade, Tier, product_of
from scheduling.domain.model.instructor import Instructor
from scheduling.domain.model.period import Period, Season
from scheduling.domain.model.team import Team
from scheduling.domain.model.timeslot import TimeSlot
from scheduling.domain.model.timetable import Timetable
from scheduling.domain.model.venue import Center, Room
from scheduling.domain.service.health import check
from scheduling.domain.service.scheduling_problem import SchedulingProblem

数学, 语文 = product_of("编程理论"), product_of("文学美育")
表 = Timetable(["08:10-10:10", "10:30-12:30"])


def 团队(tid, center, slot, who, product=数学, grade=Grade.S8):
    return Team(id=tid, center=center, campus=Center.campus_of(center),
                region="福田", grade=grade, product=product, tier=Tier.LI,
                period=Period.A, slot=TimeSlot.parse(slot), instructor=who)


def 问题(teams, calendar=None, centers=None):
    centers = centers or {c: Center(c, Center.campus_of(c), "福田",
                                    rooms=[Room(c, "R1"), Room(c, "R2")])
                          for c in {t.center for t in teams}}
    return SchedulingProblem(
        season=Season.寒暑假, teams=teams,
        instructors={"甲老师": Instructor("甲老师", {数学, 语文}),
                     "乙老师": Instructor("乙老师", {数学, 语文})},
        centers=centers, timetables={Period.A: 表}, calendar=calendar)


def test_批次内撞车能查出来():
    r = check(问题([团队("T1", "甲中心", "08:10-10:10", "甲老师"),
                    团队("T2", "乙中心", "08:10-10:10", "甲老师")]))
    assert len(r.of("H1")) == 1


def test_R1_没有日历时必须明说未检查而不是不声不响跳过():
    r = check(问题([团队("T1", "甲中心", "08:10-10:10", "甲老师")]))
    assert any("跨批次" in u and "未检查" in u for u in r.unchecked)
    assert any("只在批次内成立" in u for u in r.unchecked)


def test_R1_有日历时按真实授课日查出跨批次撞车():
    """两个批次日期重叠且共用教师 —— 分批次检查看不见这类冲突。"""
    共同日 = date(2024, 8, 5)
    cal = AcademicCalendar([
        Batch("暑假一期", Season.寒暑假, date(2024, 8, 1), date(2024, 8, 10),
              {Period.A: [共同日]}),
        Batch("暑假二期", Season.寒暑假, date(2024, 8, 3), date(2024, 8, 12),
              {Period.A: [共同日]}),
    ])
    r = check(问题([团队("T1", "甲中心", "08:10-10:10", "甲老师"),
                    团队("T2", "乙中心", "08:10-10:10", "甲老师")], calendar=cal))
    跨 = r.of("H1-跨批次")
    assert 跨 and all(v.is_verified for v in 跨)
    assert "2024-08-05" in 跨[0].detail


def test_区间相交但授课日不重叠时不算撞车():
    """学年区间有交集 ≠ 实际授课日重叠 —— 不能拿区间相交当结论。"""
    cal = AcademicCalendar([
        Batch("一期", Season.寒暑假, date(2024, 8, 1), date(2024, 8, 10),
              {Period.A: [date(2024, 8, 5)]}),
        Batch("二期", Season.寒暑假, date(2024, 8, 3), date(2024, 8, 12),
              {Period.A: [date(2024, 8, 9)]}),
    ])
    assert cal.overlapping_pairs(), "区间确实相交"
    r = check(问题([团队("T1", "甲中心", "08:10-10:10", "甲老师"),
                    团队("T2", "乙中心", "08:10-10:10", "甲老师")], calendar=cal))
    assert not r.of("H1-跨批次"), "但授课日不同天，不该报冲突"


def test_中心教室超额时标注数据是不是估计():
    c = Center("甲中心", "甲", "福田", rooms=[Room("甲中心", "估1")],
               rooms_are_estimated=True)
    r = check(问题([团队("T1", "甲中心", "08:10-10:10", "甲老师"),
                    团队("T2", "甲中心", "08:10-10:10", "乙老师")],
                   centers={"甲中心": c}))
    assert r.of("H3-中心") and "估计值" in r.of("H3-中心")[0].detail


def test_容量分两层查_报告要指明是哪一层卡住的():
    """否则「不可行」查不出源头 —— 是某栋楼教室不够，还是整个校区超了。"""
    centers = {n: Center(n, "百花", "福田", rooms=[Room(n, "R%d" % i)
                                                   for i in range(3)])
               for n in ("百花科学", "百花文学")}
    teams = [团队("T1", "百花科学", "08:10-10:10", "甲老师"),
             团队("T2", "百花文学", "08:10-10:10", "乙老师")]

    # 只有中心级：3 间教室各放 1 个班，不超
    p = 问题(teams, centers=centers)
    assert not check(p).of("H3-中心") and not check(p).of("H3-校区")

    # 加上校区级上限 1：校区这一层就超了
    p2 = 问题(teams, centers=centers)
    p2.campus_caps = {"百花": 1}
    r = check(p2)
    assert not r.of("H3-中心"), "中心级没超"
    assert r.of("H3-校区"), "校区级超了，且要单独报出来"
    assert "百花 校区" in r.of("H3-校区")[0].detail


def test_没配校区上限时不报校区违规():
    centers = {n: Center(n, "百花", "福田", rooms=[Room(n, "R1")])
               for n in ("百花科学", "百花文学")}
    r = check(问题([团队("T1", "百花科学", "08:10-10:10", "甲老师"),
                    团队("T2", "百花文学", "08:10-10:10", "乙老师")],
                   centers=centers))
    assert not r.of("H3-校区"), "没配就不该凭空造限制"


def test_缺坐标要作为未检查项列出而不是当成没问题():
    r = check(问题([团队("T1", "甲中心", "08:10-10:10", "甲老师")]))
    assert any("缺坐标" in u for u in r.unchecked)
