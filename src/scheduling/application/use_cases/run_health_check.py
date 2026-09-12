"""用例：体检一份排班。

给现有手工排班打基线分，也用来验证求解结果 —— 两者用**同一把尺子**。
"""
from __future__ import annotations

from dataclasses import dataclass

from ...domain.service.health import HealthReport, check
from ...domain.service.scheduling_problem import SchedulingProblem


@dataclass
class HealthSummary:
    total_score: int
    breakdown: dict
    violations: list
    unchecked: list
    verified_count: int
    candidate_count: int

    @classmethod
    def of(cls, report: HealthReport) -> "HealthSummary":
        return cls(
            total_score=report.score.total,
            breakdown=dict(report.score.breakdown),
            violations=[(v.rule, v.detail, v.label) for v in report.violations],
            unchecked=list(report.unchecked),
            verified_count=report.verified_count,
            candidate_count=report.candidate_count)


class RunHealthCheck:
    def __call__(self, problem: SchedulingProblem, teams=None) -> HealthSummary:
        return HealthSummary.of(check(problem, teams))
