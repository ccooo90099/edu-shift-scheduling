"""用例：跑一次排班，并把结果落盘。

后台执行，进度靠轮询 —— 求解在大候选池下可能几分钟不收敛，
HTTP 请求扛不住。

导出器以参数传进来，所以这一层不直接绑死 xlsx —— 换 csv 或别的格式
不用改这里。
"""
from __future__ import annotations

import traceback
from datetime import datetime

from ...domain.service.health import check
from ...domain.service.scheduling_problem import SchedulingProblem
from ...infrastructure.solver.cpsat import CpSatScheduler
from ..dto import SolveTask, TaskStatus


class RunSolve:
    def __init__(self, tasks, *, time_limit: float = 60.0, workers: int = 8,
                 exporter=None):
        self._tasks = tasks
        self._time_limit = time_limit
        self._workers = workers
        self._exporter = exporter

    def __call__(self, task: SolveTask, problem: SchedulingProblem,
                 output_path=None) -> SolveTask:
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now()
        task.error = ""
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

            # 体检用的是**同一把尺子**（score_schedule），所以报告里的分数
            # 和求解目标对得上，不会出现两个数
            report = check(problem, outcome.teams)
            for u in report.unchecked:
                task.notes.append("未检查：%s" % u)
            if report.violations:
                task.notes.append(
                    "体检查出 %d 条违规（已验证 %d / 估算候选 %d）"
                    % (len(report.violations), report.verified_count,
                       report.candidate_count))

            if self._exporter is not None and output_path is not None:
                self._exporter(output_path, outcome.teams, report,
                               problem.season, outcome)
                task.output_path = str(output_path)

            task.status = TaskStatus.DONE
        except Exception as exc:                      # noqa: BLE001
            task.status = TaskStatus.FAILED
            task.error = "%s: %s" % (type(exc).__name__, exc)
            task.notes = [traceback.format_exc(limit=4)]
        finally:
            task.finished_at = datetime.now()
            self._tasks.update(task)
        return task
