"""组装 —— 把仓储、用例接到一起。

依赖注入集中在这一个地方。路由函数只拿 `Container`，不自己 new 任何东西，
所以测试里换成内存实现只要换这一个对象。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from ...application.use_cases.check_readiness import CheckReadiness
from ...application.use_cases.run_health_check import RunHealthCheck
from ...application.use_cases.run_solve import RunSolve
from ...infrastructure.persistence.sqlite import (
    SqliteCalendarRepository, SqliteCenterRepository,
    SqliteInstructorRepository, SqliteTaskRepository, connect)


@dataclass
class Container:
    centers: object
    instructors: object
    calendars: object
    tasks: object
    data_dir: Path

    @property
    def check_readiness(self) -> CheckReadiness:
        return CheckReadiness(self.centers, self.instructors, self.calendars)

    @property
    def run_solve(self) -> RunSolve:
        return RunSolve(self.tasks)

    @property
    def run_health_check(self) -> RunHealthCheck:
        return RunHealthCheck()

    @classmethod
    def build(cls, data_dir=None) -> "Container":
        root = Path(data_dir or os.environ.get("SCHEDULING_DATA", "data"))
        root.mkdir(parents=True, exist_ok=True)
        conn = connect(root / "scheduling.db")
        return cls(
            centers=SqliteCenterRepository(conn),
            instructors=SqliteInstructorRepository(conn),
            calendars=SqliteCalendarRepository(conn),
            tasks=SqliteTaskRepository(conn),
            data_dir=root)
