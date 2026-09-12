"""排班问题 —— 求解器的输入，以及评分的唯一口径。

**求解和体检必须共用这里的评分函数。** 历史教训：两侧各自实现转场计数，
同一份排班一个报 19 一个报 25，谁也没法验证谁。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..model.academic_calendar import AcademicCalendar
from ..model.cohort import Cohort, CohortKey
from ..model.instructor import Instructor
from ..model.period import Period, Season
from ..model.team import Team
from ..model.timetable import Timetable
from ..model.venue import Center
from ..policy.adjacency import AdjacencyGrade, AdjacencyPolicy
from ..policy.capacity import CapacityPolicy
from ..policy.golden_hours import GoldenHoursPolicy
from ..policy.travel import count_transfers
from ..policy.weights import Weights


@dataclass
class SchedulingProblem:
    """一次求解的全部输入。"""
    season: Season
    teams: list[Team]
    instructors: dict[str, Instructor]
    centers: dict[str, Center]
    #: 期位 → 那天开哪几档课。春秋季周五只开 18:30 一档，靠它表达。
    timetables: dict[Period, Timetable] = field(default_factory=dict)
    cohorts: dict[CohortKey, Cohort] = field(default_factory=dict)
    calendar: AcademicCalendar | None = None
    weights: Weights = field(default_factory=Weights)
    golden: GoldenHoursPolicy = field(default_factory=GoldenHoursPolicy)
    #: 区域 → 相邻区域。空 = 所有不同区一律按最差档算（保守兜底）。
    region_adjacency: dict = field(default_factory=dict)
    #: 校区 → 同时最多开几个班。空 = 只按中心的教室数限制。
    campus_caps: dict = field(default_factory=dict)

    @property
    def capacity(self) -> CapacityPolicy:
        return CapacityPolicy.from_centers(self.centers, self.campus_caps)

    def timetable_for(self, period: Period) -> Timetable:
        return self.timetables[period]

    def adjacency_for(self, period: Period) -> AdjacencyPolicy:
        return AdjacencyPolicy(self.timetable_for(period))

    def candidate_slots(self, team: Team, period: Period):
        """这个团队在这个期位能排的时段。

        黄金时段过滤要与**当天开门时段取交集** —— 黄金只按时间定义，
        不代表可以忽略那天开不开门。
        """
        return self.golden.candidate_slots(
            self.timetable_for(period).slots, team.is_promotional)

    @property
    def campus_of(self) -> dict[str, str]:
        return {n: c.campus for n, c in self.centers.items()}

    @property
    def region_of(self) -> dict[str, str]:
        return {n: c.region for n, c in self.centers.items() if c.region}


@dataclass
class Score:
    """一份排班的得分明细。求解目标与体检报告用的是同一个。"""
    breakdown: dict[str, int] = field(default_factory=dict)
    weights: Weights = field(default_factory=Weights)

    def add(self, key: str, count: int) -> None:
        if count:
            self.breakdown[key] = self.breakdown.get(key, 0) + count

    @property
    def total(self) -> int:
        return sum(self.weights[k] * n for k, n in self.breakdown.items())

    def report(self) -> str:
        lines = ["总分 %d" % self.total]
        for k, n in sorted(self.breakdown.items(),
                           key=lambda kv: -self.weights[kv[0]] * kv[1]):
            lines.append("  %-18s %5d × %-6d = %d"
                         % (k, n, self.weights[k], n * self.weights[k]))
        return "\n".join(lines)


def instructor_day_plan(teams):
    """按时间排序的某人某日行程 —— 转场与空档判定的共同基础。"""
    return sorted((t for t in teams if t.is_scheduled),
                  key=lambda t: t.slot.start)


def score_schedule(problem: SchedulingProblem, teams=None) -> Score:
    """给一份排班打分。**这是唯一的评分口径。**"""
    teams = list(problem.teams if teams is None else teams)
    score = Score(weights=problem.weights)

    score.add("排不上团队", sum(1 for t in teams if not t.is_scheduled))

    # —— 转场：按相邻课之间实际发生的中心变更计，A→B→A = 2 ——
    by_person: dict[tuple, list[Team]] = {}
    for t in teams:
        if t.is_scheduled:
            by_person.setdefault((t.instructor, t.period), []).append(t)

    transfers = 0
    extra_rooms = 0
    gaps = 0
    for (_person, period), day in by_person.items():
        plan = instructor_day_plan(day)
        transfers += count_transfers([t.center for t in plan])
        timetable = problem.timetable_for(period)
        for a, b in zip(plan, plan[1:]):
            gaps += timetable.slots_between(a.slot, b.slot)
        # S11 额外使用教室数：distinct−1，按 (指导员, 中心, 教学日) 聚合。
        # 注意这不是「换教室次数」—— A→B→A 在这个口径下记 1 不是 2。
        by_center: dict[str, set] = {}
        for t in plan:
            if t.room:
                by_center.setdefault(t.center, set()).add(t.room)
        extra_rooms += sum(max(0, len(rs) - 1) for rs in by_center.values())

    score.add("转场一次", transfers)
    score.add("课表空档一段", gaps)
    score.add("额外使用教室", extra_rooms)

    # —— 期位偏好与延续性 ——
    score.add("排在期位B", sum(1 for t in teams if t.period is Period.B))
    score.add("期位与历史不符",
              sum(1 for t in teams if t.original_period
                  and t.period and t.period is not t.original_period))

    # —— 连堂与并发，按报读组合的估计人数加权 ——
    by_cohort: dict[CohortKey, list[Team]] = {}
    for t in teams:
        by_cohort.setdefault(t.cohort_key, []).append(t)

    split, unadjacent, concurrent_cost = 0, 0, 0
    for key, group in by_cohort.items():
        cohort = problem.cohorts.get(key)
        periods = {t.period for t in group if t.period}
        if len(periods) > 1:
            split += 1
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                if a.product is b.product:
                    continue
                pair_size = (cohort.headcount_taking_both(a.product, b.product)
                             if cohort else 0)
                if not (a.is_scheduled and b.is_scheduled):
                    continue
                if a.period is not b.period:
                    continue
                if a.slot.overlaps(b.slot):
                    # 原 H2 降级为 S8：撞了要扣分，扣多少看伤到多少人
                    concurrent_cost += pair_size
                elif pair_size:
                    grade = problem.adjacency_for(a.period).grade(a.slot, b.slot)
                    unadjacent += int(grade) * (1 if pair_size else 0)

    score.add("挪到另一期位", split)
    score.add("连堂未达标", unadjacent)
    score.add("并发每受影响学生", concurrent_cost)

    # —— 工作量峰值 ——
    load: dict[str, int] = {}
    for t in teams:
        if t.instructor:
            load[t.instructor] = load.get(t.instructor, 0) + 1
    if load:
        score.add("工作量峰值", max(load.values()))

    return score
