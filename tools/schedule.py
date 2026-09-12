#!/usr/bin/env python3
"""自动排班。

    python tools/schedule.py 团队清单.xlsx --config config/rules.yaml --out 排班.xlsx
    python tools/schedule.py 团队清单.xlsx --season 春秋季 --time-limit 300

输出一个 Excel：总览 / 排班明细 / 看板 / 老师课表 / 问题清单。

**求解状态会如实打印。** FEASIBLE（有解但没证明最优）和 OPTIMAL（证明了最优）
是两回事，别把前者当成「排好了」。
"""
import argparse
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "src"))

try:
    from console import force_utf8
except ImportError:          # console.py 缺失时也不该崩 —— 它只是 6 行标准库
    def force_utf8():
        for _stream in (sys.stdout, sys.stderr):
            try:
                _stream.reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, ValueError, OSError):
                pass

from scheduling.application.use_cases.build_problem import BuildProblem  # noqa: E402
from scheduling.domain.model.period import Season  # noqa: E402
from scheduling.domain.service.health import check  # noqa: E402
from scheduling.infrastructure.solver.cpsat import CpSatScheduler  # noqa: E402
from scheduling.infrastructure.spreadsheet.export import write_workbook  # noqa: E402


def main():
    force_utf8()
    ap = argparse.ArgumentParser(description="自动排班")
    ap.add_argument("schedule", help="待排团队清单（用现有排班明细即可）")
    ap.add_argument("--config", default="config/rules.yaml")
    ap.add_argument("--out", default="排班结果.xlsx")
    ap.add_argument("--season", choices=[s.value for s in Season],
                    default=Season.寒暑假.value)
    ap.add_argument("--time-limit", type=int, default=120)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    season = Season(args.season)
    problem = BuildProblem()(args.schedule, args.config, season=season)
    print("读入 %d 个团队、%d 位指导员、%d 个中心"
          % (len(problem.teams), len(problem.instructors), len(problem.centers)))
    print(problem.weights.effective_report())

    outcome = CpSatScheduler(problem, time_limit=args.time_limit,
                             workers=args.workers, seed=args.seed).solve()
    print("\n求解状态 %s，用时 %.1f 秒" % (outcome.status, outcome.elapsed_seconds))
    for note in outcome.notes:
        print("  ⚠ %s" % note)
    if outcome.objective is not None:
        print("  目标值 %.0f，下界 %.0f" % (outcome.objective, outcome.best_bound))

    report = check(problem, outcome.teams)
    print("\n%s" % report.score.report())
    if report.violations:
        print("\n违规 %d 条（已验证 %d / 估算候选 %d）"
              % (len(report.violations), report.verified_count,
                 report.candidate_count))
        for v in report.violations[:10]:
            print("  [%s·%s] %s" % (v.rule, v.label, v.detail))
    for u in report.unchecked:
        print("\n⚠ 未检查：%s" % u)

    write_workbook(args.out, outcome.teams, report, season, outcome)
    print("\n写出 %s" % args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
