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
from ...infrastructure.spreadsheet.export import write_workbook
from ...infrastructure.spreadsheet import result_json
from ...infrastructure.persistence.sqlite import (
    SqliteCalendarRepository, SqliteCenterRepository,
    SqliteInstructorRepository, SqliteTaskRepository, connect)


def _export_both(path, teams, report, season, outcome):
    """xlsx 给人下载，json 给网页按日期展开 —— 同一次结果写两份。"""
    write_workbook(path, teams, report, season, outcome)
    result_json.dump(Path(path).with_suffix(".json"), teams, season, outcome)


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
        # 默认给 120 秒。求解很可能到点还没证明最优 —— 界面会如实
        # 显示 FEASIBLE 和与下界的差距，不会把它说成「排好了」。
        return RunSolve(self.tasks, time_limit=float(
            os.environ.get("SCHEDULING_TIME_LIMIT", "120")),
            workers=2, exporter=_export_both)

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
