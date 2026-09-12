"""应用层数据契约。

界面层只认这些结构，不直接碰领域对象 —— 领域模型可以自由重构，
不会把接口一起改掉。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"

    @property
    def label(self) -> str:
        return {"pending": "排队中", "running": "求解中",
                "done": "已完成", "failed": "失败"}[self.value]

    @property
    def is_terminal(self) -> bool:
        return self in (TaskStatus.DONE, TaskStatus.FAILED)


@dataclass
class SolveTask:
    """一次求解任务。求解要跑很久，必须后台异步 + 轮询。"""
    id: str
    name: str
    season: str
    status: TaskStatus = TaskStatus.PENDING
    config: dict = field(default_factory=dict)
    input_path: str = ""
    output_path: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    started_at: datetime | None = None
    finished_at: datetime | None = None

    #: 求解状态：OPTIMAL / FEASIBLE / INFEASIBLE / UNKNOWN。
    #: 与 status 是两回事 —— 任务「已完成」不代表解「最优」。
    solver_status: str = ""
    objective: float | None = None
    best_bound: float | None = None
    score_breakdown: dict = field(default_factory=dict)
    unplaced: int = 0
    notes: list[str] = field(default_factory=list)
    error: str = ""

    @property
    def elapsed_seconds(self) -> float:
        if not self.started_at:
            return 0.0
        end = self.finished_at or datetime.now()
        return (end - self.started_at).total_seconds()

    @property
    def gap_hint(self) -> str:
        """还有多少改善空间。把 FEASIBLE 说成「排好了」是误导。"""
        if self.solver_status == "OPTIMAL":
            return "已证明最优"
        if self.objective is None or self.best_bound is None:
            return "无解或未开始"
        if self.objective <= 0:
            return "目标为 0"
        gap = (self.objective - self.best_bound) / abs(self.objective) * 100
        return "未证明最优，与下界还差 %.1f%%" % gap


@dataclass
class ReadinessView:
    """顶部常驻告警条的视图数据。"""
    code: str
    severity: str
    summary: str
    consequence: str
    count: int
    fix_route: str

    @property
    def is_blocking_quality(self) -> bool:
        return self.severity == "warning"
