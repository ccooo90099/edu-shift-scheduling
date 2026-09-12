"""CP-SAT 求解器适配。

这是**基础设施**：它把领域对象翻译成 OR-Tools 的变量和约束，求完再翻译回来。
业务规则一条都不写在这里 —— 全部来自 `domain/policy`。换掉求解器，
领域层一行不用改。

决策变量：每个团队一组 `(期位, 时段, 指导员, 教室)`。
"""
from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field

from ortools.sat.python import cp_model

from ...domain.model.period import Period
from ...domain.model.team import Team
from ...domain.policy.travel import count_transfers
from ...domain.service.scheduling_problem import SchedulingProblem, score_schedule


@dataclass
class SolveOutcome:
    """求解结果。

    **状态必须如实汇报。** FEASIBLE（有解但没证明最优）和 OPTIMAL（证明了最优）
    是两回事，把 FEASIBLE 说成「排好了」是误导。best_bound 让人判断
    还有多少改善空间。
    """
    status: str
    teams: list[Team]
    objective: float | None = None
    best_bound: float | None = None
    elapsed_seconds: float = 0.0
    score_breakdown: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def is_proven_optimal(self) -> bool:
        return self.status == "OPTIMAL"

    @property
    def all_placed(self) -> bool:
        return all(t.is_scheduled for t in self.teams)


_STATUS = {
    cp_model.OPTIMAL: "OPTIMAL",
    cp_model.FEASIBLE: "FEASIBLE",
    cp_model.INFEASIBLE: "INFEASIBLE",
    cp_model.MODEL_INVALID: "MODEL_INVALID",
    cp_model.UNKNOWN: "UNKNOWN",
}


class CpSatScheduler:
    """把 SchedulingProblem 求解成一份排班。"""

    def __init__(self, problem: SchedulingProblem, *,
                 time_limit: float = 60.0, workers: int = 8, seed: int = 0):
        self.p = problem
        self.time_limit = time_limit
        self.workers = workers
        self.seed = seed

    # ------------------------------------------------------------ 建模

    def _build(self):
        m = cp_model.CpModel()
        p = self.p
        w = p.weights

        # 每个团队的候选 (期位, 时段) 组合
        self.placements: dict[str, list] = {}
        self.x: dict[tuple, cp_model.IntVar] = {}
        self.placed: dict[str, cp_model.IntVar] = {}

        for t in p.teams:
            options = []
            for period in p.timetables:
                for slot in p.candidate_slots(t, period):
                    options.append((period, slot))
            self.placements[t.id] = options
            for period, slot in options:
                self.x[(t.id, period, slot)] = m.NewBoolVar(
                    "x_%s_%s_%s" % (t.id, period.value, slot.text))
            self.placed[t.id] = m.NewBoolVar("placed_%s" % t.id)
            m.Add(sum(self.x[(t.id, pe, s)] for pe, s in options)
                  == self.placed[t.id])

        # 指导员分配
        self.y: dict[tuple, cp_model.IntVar] = {}
        self.candidates: dict[str, list[str]] = {}
        for t in p.teams:
            names = [n for n, i in p.instructors.items() if i.can_teach(t)]
            self.candidates[t.id] = names
            for n in names:
                self.y[(t.id, n)] = m.NewBoolVar("y_%s_%s" % (t.id, n))
            m.Add(sum(self.y[(t.id, n)] for n in names) == self.placed[t.id])

        self._hard_constraints(m)
        objective = self._objective(m)
        m.Minimize(objective)
        return m

    def _hard_constraints(self, m):
        p = self.p

        # H5 年级 → 可开产品
        for t in p.teams:
            if not t.is_valid_product():
                m.Add(self.placed[t.id] == 0)

        # H1 一个指导员同一时刻只能带一个团队。
        # 按**真实时间重叠组**约束，不按时段标签 —— 标签不同但时间重叠的
        # 两节课，逐标签判定会漏掉。
        for period, timetable in p.timetables.items():
            for group in timetable.concurrent_groups:
                for name in p.instructors:
                    terms = []
                    for t in p.teams:
                        if name not in self.candidates.get(t.id, ()):
                            continue
                        for slot in group:
                            key = (t.id, period, slot)
                            if key in self.x:
                                z = m.NewBoolVar("")
                                m.AddMultiplicationEquality(
                                    z, [self.x[key], self.y[(t.id, name)]])
                                terms.append(z)
                    if len(terms) > 1:
                        m.Add(sum(terms) <= 1)

        # H3 场地容量。两层，都可选，同时生效时自然取更严的：
        #   ① 中心级：教室数
        #   ② 校区级：整个校区同时最多开几个班
        # 粒度不固定所以都做成配置；没配的那一层不加约束，
        # **不要凭空造一个限制出来**。
        capacity = p.capacity
        by_center = defaultdict(list)
        by_campus = defaultdict(list)
        for t in p.teams:
            by_center[t.center].append(t)
            by_campus[t.campus].append(t)

        def limit_concurrency(members, limit):
            if limit is None:
                return
            for period, timetable in p.timetables.items():
                for group in timetable.concurrent_groups:
                    terms = [self.x[(t.id, period, s)]
                             for t in members for s in group
                             if (t.id, period, s) in self.x]
                    if terms:
                        m.Add(sum(terms) <= limit)

        for center_name, members in by_center.items():
            limit_concurrency(members, capacity.center_limit(center_name))
        for campus_name, members in by_campus.items():
            limit_concurrency(members, capacity.campus_limit(campus_name))

        # 指导员单日最多节数
        for name, inst in p.instructors.items():
            for period in p.timetables:
                terms = [self.x[(t.id, period, s)]
                         for t in p.teams
                         if name in self.candidates.get(t.id, ())
                         for pe, s in self.placements[t.id] if pe is period
                         if (t.id, period, s) in self.x]
                if terms:
                    m.Add(sum(terms) <= inst.max_sessions_per_day * len(terms))

        # 锁定的团队固定成常量 —— 全局软罚分保证不了小改动
        for t in p.teams:
            if t.is_locked and t.slot and t.period:
                key = (t.id, t.period, t.slot)
                if key in self.x:
                    m.Add(self.x[key] == 1)
                if t.instructor and (t.id, t.instructor) in self.y:
                    m.Add(self.y[(t.id, t.instructor)] == 1)

    def _objective(self, m):
        p, w = self.p, self.p.weights
        terms = []

        # 排不上
        for t in p.teams:
            terms.append(w["排不上团队"] * (1 - self.placed[t.id]))

        # 期位 B 次之（周六更好排）
        for t in p.teams:
            for period, slot in self.placements[t.id]:
                if period is Period.B:
                    terms.append(w["排在期位B"] * self.x[(t.id, period, slot)])

        # 期位与历史不符
        for t in p.teams:
            if not t.original_period:
                continue
            for period, slot in self.placements[t.id]:
                if period is not t.original_period:
                    terms.append(w["期位与历史不符"] * self.x[(t.id, period, slot)])

        # 连堂与并发 —— 按报读组合的估计人数加权
        by_cohort = defaultdict(list)
        for t in p.teams:
            by_cohort[t.cohort_key].append(t)

        for key, group in by_cohort.items():
            cohort = p.cohorts.get(key)
            for i, a in enumerate(group):
                for b in group[i + 1:]:
                    if a.product is b.product:
                        continue
                    pair_size = (cohort.headcount_taking_both(a.product, b.product)
                                 if cohort else 0)
                    for period, timetable in p.timetables.items():
                        adj = p.adjacency_for(period)
                        for sa in p.candidate_slots(a, period):
                            for sb in p.candidate_slots(b, period):
                                ka = (a.id, period, sa)
                                kb = (b.id, period, sb)
                                if ka not in self.x or kb not in self.x:
                                    continue
                                if sa.overlaps(sb) and pair_size == 0:
                                    continue
                                both = m.NewBoolVar("")
                                m.AddMultiplicationEquality(
                                    both, [self.x[ka], self.x[kb]])
                                if sa.overlaps(sb):
                                    cost = w["并发每受影响学生"] * pair_size
                                else:
                                    cost = (w["连堂未达标"]
                                            * int(adj.grade(sa, sb)) * pair_size)
                                if cost:
                                    terms.append(cost * both)
        return sum(terms) if terms else 0

    # ------------------------------------------------------------ 求解

    def solve(self) -> SolveOutcome:
        started = time.monotonic()
        m = self._build()
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = float(self.time_limit)
        solver.parameters.num_search_workers = int(self.workers)
        if self.seed:
            solver.parameters.random_seed = int(self.seed)
        status = solver.Solve(m)
        elapsed = time.monotonic() - started

        name = _STATUS.get(status, str(status))
        teams = [self._apply(t, solver) for t in self.p.teams] \
            if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else list(self.p.teams)

        notes = []
        if name == "FEASIBLE":
            notes.append("有解，但**未证明最优** —— best_bound 说明还有多少改善空间")
        if name == "UNKNOWN":
            notes.append("限时内没找到解。**这不等于无解**，加时间或换 seed 可能就有")

        score = score_schedule(self.p, teams) if teams else None
        return SolveOutcome(
            status=name, teams=teams,
            objective=solver.ObjectiveValue() if status in (
                cp_model.OPTIMAL, cp_model.FEASIBLE) else None,
            best_bound=solver.BestObjectiveBound() if status in (
                cp_model.OPTIMAL, cp_model.FEASIBLE) else None,
            elapsed_seconds=elapsed,
            score_breakdown=dict(score.breakdown) if score else {},
            notes=notes)

    def _apply(self, team: Team, solver) -> Team:
        for period, slot in self.placements[team.id]:
            if solver.Value(self.x[(team.id, period, slot)]):
                team.period, team.slot = period, slot
                break
        else:
            team.period = team.slot = None
        for name in self.candidates.get(team.id, ()):
            if solver.Value(self.y[(team.id, name)]):
                team.instructor = name
                break
        else:
            team.instructor = None
        return team
