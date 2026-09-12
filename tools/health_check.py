#!/usr/bin/env python3
"""体检一份排班：算违规、打分、指出因缺数据而没能检查的项。

    python tools/health_check.py 排班明细.xlsx --config config/rules.yaml

给现有手工排班打基线分，也用来验证求解结果 —— **两者用同一把尺子**。
"""
import argparse
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "src"))

try:
    from console import force_utf8
except ImportError:
    def force_utf8():
        for _stream in (sys.stdout, sys.stderr):
            try:
                _stream.reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, ValueError, OSError):
                pass

from scheduling.application.use_cases.build_problem import BuildProblem  # noqa: E402
from scheduling.domain.model.period import Period, Season  # noqa: E402
from scheduling.domain.service.health import check  # noqa: E402


def main():
    force_utf8()
    ap = argparse.ArgumentParser(description="体检一份排班")
    ap.add_argument("schedule")
    ap.add_argument("--config", default="config/rules.yaml")
    ap.add_argument("--season", choices=[s.value for s in Season],
                    default=Season.寒暑假.value)
    args = ap.parse_args()

    season = Season(args.season)
    problem = BuildProblem()(args.schedule, args.config, season=season)

    # 体检看的是**原样的**排班，所以把原时段与原指导员填回决策位
    for t in problem.teams:
        t.slot = t.original_slot
        t.instructor = t.original_instructor
        t.period = t.original_period or Period.A

    report = check(problem)
    print("团队 %d 个，其中 %d 个原表没排上"
          % (len(problem.teams),
             sum(1 for t in problem.teams if not t.is_scheduled)))
    print("\n%s" % report.score.report())

    if report.violations:
        print("\n违规 %d 条（已验证 %d / 估算候选 %d）"
              % (len(report.violations), report.verified_count,
                 report.candidate_count))
        by_rule = {}
        for v in report.violations:
            by_rule.setdefault(v.rule, []).append(v)
        for rule, items in sorted(by_rule.items()):
            print("\n  %s —— %d 条" % (rule, len(items)))
            for v in items[:5]:
                print("    [%s] %s" % (v.label, v.detail))
            if len(items) > 5:
                print("    …… 还有 %d 条" % (len(items) - 5))
    else:
        print("\n没有查出违规。")

    if report.unchecked:
        print("\n⚠ 以下项**因为缺数据而没能检查**，不等于没问题：")
        for u in report.unchecked:
            print("  · %s" % u)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
