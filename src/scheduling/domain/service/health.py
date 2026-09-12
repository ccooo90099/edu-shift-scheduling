"""体检 —— 对任意一份排班（手工的或求解出的）算违规和得分。

**和求解器共用 `score_schedule`**，不另起一套评分。

R1：`(段次, 周)` 不是「一个教学日」。批次在日期上可能重叠且共用教师，
分批次检查会让跨批次撞车完全不被发现。有真实日历时按日期展开做全局检查；
**没有日历时必须说明「未检查」，不能不声不响地跳过。**
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from ..model.period import Period
from ..policy.travel import count_transfers
from .scheduling_problem import SchedulingProblem, Score, score_schedule


@dataclass(frozen=True)
class Violation:
    rule: str
    detail: str
    #: 已验证 / 估算候选 —— 两者绝不能混为一谈
    is_verified: bool = True

    @property
    def label(self) -> str:
        return "已验证" if self.is_verified else "估算候选（需真实授课日核查）"


@dataclass
class HealthReport:
    score: Score
    violations: list[Violation] = field(default_factory=list)
    #: 因为缺数据而**没能检查**的项 —— 必须显式列出
    unchecked: list[str] = field(default_factory=list)

    def of(self, rule: str) -> list[Violation]:
        return [v for v in self.violations if v.rule == rule]

    @property
    def verified_count(self) -> int:
        return sum(1 for v in self.violations if v.is_verified)

    @property
    def candidate_count(self) -> int:
        return sum(1 for v in self.violations if not v.is_verified)


def _clashes_within(teams) -> list[Violation]:
    """同一时刻同一个人在两个地方。"""
    out = []
    by_person: dict[tuple, list] = {}
    for t in teams:
        if t.is_scheduled:
            by_person.setdefault((t.instructor, t.period), []).append(t)
    for (person, period), group in by_person.items():
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                if a.slot.overlaps(b.slot):
                    out.append(Violation(
                        "H1", "%s 在 %s 同时带 %s(%s) 与 %s(%s)"
                        % (person, period.value, a.id, a.center, b.id, b.center)))
    return out


def check(problem: SchedulingProblem, teams=None) -> HealthReport:
    teams = list(problem.teams if teams is None else teams)
    report = HealthReport(score=score_schedule(problem, teams))

    report.violations.extend(_clashes_within(teams))

    # H3 场地容量，两层分别查 —— 报告要指明是哪一层卡住的，
    # 否则「不可行」查不出源头
    capacity = problem.capacity
    for period, timetable in problem.timetables.items():
        for group in timetable.concurrent_groups:
            by_center: dict[str, int] = {}
            by_campus: dict[str, int] = {}
            for t in teams:
                if t.is_scheduled and t.period is period and t.slot in group:
                    by_center[t.center] = by_center.get(t.center, 0) + 1
                    by_campus[t.campus] = by_campus.get(t.campus, 0) + 1

            for center_name, n in by_center.items():
                limit = capacity.center_limit(center_name)
                if limit is not None and n > limit:
                    center = problem.centers.get(center_name)
                    kind = ("（教室数为估计值，非实测清单）"
                            if center and center.rooms_are_estimated else "")
                    report.violations.append(Violation(
                        "H3-中心", "%s 在 %s 同时开 %d 个班，超过 %d 间教室%s"
                        % (center_name, group[0].text, n, limit, kind)))

            for campus_name, n in by_campus.items():
                limit = capacity.campus_limit(campus_name)
                if limit is not None and n > limit:
                    report.violations.append(Violation(
                        "H3-校区", "%s 校区在 %s 同时开 %d 个班，超过上限 %d"
                        % (campus_name, group[0].text, n, limit)))

    # H4 资质
    for t in teams:
        if t.instructor:
            inst = problem.instructors.get(t.instructor)
            if inst and not inst.can_teach(t):
                report.violations.append(Violation(
                    "H4", "%s 不能教 %s（%s）" % (t.instructor, t.product.name, t.id)))

    # H5 年级 → 可开产品
    for t in teams:
        if not t.is_valid_product():
            report.violations.append(Violation(
                "H5", "%s 不该开 %s（%s）" % (t.grade.value, t.product.name, t.id)))

    # R1 跨批次
    calendar = problem.calendar
    if calendar is None or calendar.is_empty:
        report.unchecked.append(
            "跨批次指导员撞车：**未检查**。批次在日期上可能重叠且共用教师，"
            "没有学年日历就展不开成真实日期。所有「无冲突」的结论"
            "**只在批次内成立**。")
    else:
        report.violations.extend(_cross_batch(calendar, teams))

    # 坐标缺失导致的降级
    missing = [c.name for c in problem.centers.values() if not c.has_coordinate]
    if missing:
        report.unchecked.append(
            "转场时间：%d 个中心缺坐标，只能按同校区/同区域/跨区域三档粗判，"
            "「赶不赶得及」未真正检查。" % len(missing))

    return report


def _cross_batch(calendar, teams) -> list[Violation]:
    """按真实授课日展开，找同一天同一时刻的撞车。

    ⚠️ **学年区间相交 ≠ 实际授课日重叠。** 只有比对到具体日期的才算已验证。
    """
    out = []
    occupied: dict[tuple, list] = {}
    for batch in calendar:
        for period in (Period.A, Period.B):
            for day in batch.dates_of(period):
                for t in teams:
                    if t.is_scheduled and t.period is period:
                        occupied.setdefault((t.instructor, day), []).append((batch, t))
    for (person, day), items in occupied.items():
        for i, (ba, a) in enumerate(items):
            for bb, b in items[i + 1:]:
                if ba is bb or not a.slot.overlaps(b.slot):
                    continue
                out.append(Violation(
                    "H1-跨批次",
                    "%s 在 %s 同时带 %s(%s·%s) 与 %s(%s·%s)"
                    % (person, day, a.id, a.center, ba.name,
                       b.id, b.center, bb.name),
                    is_verified=True))
    return out
