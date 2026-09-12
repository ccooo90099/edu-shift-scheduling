"""用例：跑一次排班。

后台执行，进度靠轮询 —— 求解在大候选池下可能几分钟不收敛，
HTTP 请求扛不住。
"""
from __future__ import annotations

import traceback
from datetime import datetime

from ...domain.service.scheduling_problem import SchedulingProblem
from ...infrastructure.solver.cpsat import CpSatScheduler
from ..dto import SolveTask, TaskStatus


class RunSolve:
    def __init__(self, tasks, *, time_limit: float = 60.0, workers: int = 8):
        self._tasks = tasks
        self._time_limit = time_limit
        self._workers = workers

    def __call__(self, task: SolveTask, problem: SchedulingProblem) -> SolveTask:
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now()
        self._tasks.update(task)
        try:
            outcome = CpSatScheduler(
                problem, time_limit=self._time_limit,
                workers=self._workers).solve()
            task.solver_status = outcome.status
            task.objective = outcome.objective
            task.best_bound = outcome.best_bound
            task.score_breakdown = outcome.score_breakdown
            task.unplaced = sum(1 for t in outcome.teams if not t.is_scheduled)
            task.notes = list(outcome.notes)
            task.status = TaskStatus.DONE
        except Exception as exc:                      # noqa: BLE001
            task.status = TaskStatus.FAILED
            task.error = "%s: %s" % (type(exc).__name__, exc)
            task.notes = [traceback.format_exc(limit=3)]
        finally:
            task.finished_at = datetime.now()
            self._tasks.update(task)
        return task
