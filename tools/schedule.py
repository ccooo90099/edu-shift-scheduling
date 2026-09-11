#!/usr/bin/env python3
"""自动排班。

    # 从零重排：拿现有明细当待排清单，时段和主指导员作废重新定
    python tools/schedule.py 排班明细.xlsx --config config/rules.yaml --out 新排班.xlsx

    # 修复模式：在原排班上做最小改动
    python tools/schedule.py 排班明细.xlsx --mode repair --out 修复后.xlsx

输出一个 Excel：总览 / 排班明细 / 看板 / 老师课表 / 问题清单。
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from console import force_utf8   # noqa: E402
from engine import load_config   # noqa: E402
from engine.data import load_schedule   # noqa: E402
from engine.inputs import derive_instructors, derive_rooms, derive_teams   # noqa: E402
from engine.output import write_workbook   # noqa: E402
from engine.solver import solve   # noqa: E402


def main():
    force_utf8()
    ap = argparse.ArgumentParser(description="自动排班")
    ap.add_argument("schedule", help="待排团队清单（用现有排班明细即可）")
    ap.add_argument("--config", default="config/rules.yaml")
    ap.add_argument("--sheet", default=None)
    ap.add_argument("--out", default="排班结果.xlsx")
    ap.add_argument("--mode", choices=["rebuild", "repair"], default="rebuild",
                    help="rebuild = 从零重排（默认）；repair = 在原排班上最小改动")
    ap.add_argument("--段次", help="只排某个段次，逗号分隔")
    ap.add_argument("--time-limit", type=int, default=120, help="每个子问题最多算多少秒")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--可去中心", default="不限", choices=["不限", "历史"],
                    help="历史 = 老师只去他在原数据里去过的中心")
    args = ap.parse_args()

    cfg = load_config(args.config)
    df = load_schedule(args.schedule, cfg, args.sheet)
    if args.段次:
        keep = {x.strip() for x in args.段次.split(",")}
        df = df[df["段次"].isin(keep)]
        if df.empty:
            sys.exit("没有匹配的段次：%s" % "、".join(sorted(keep)))

    teams = derive_teams(df)
    instructors = derive_instructors(df, 可去中心=args.可去中心)
    rooms = derive_rooms(df)
    seed = {t.团队ID: (t.原时段, t.原主指导员) for t in teams}

    weights = None
    if args.mode == "repair":
        weights = {"与原排班不同": 40}

    print("待排 %d 个团队 | 老师 %d 位 | 中心 %d 个 | 模式 %s\n"
          % (len(teams), len(instructors), len(rooms), args.mode))

    result = solve(teams, instructors, rooms, cfg, seed=seed,
                   time_limit=args.time_limit, workers=args.workers,
                   weights=weights, log=lambda m: print("  " + m))

    print("\n%s，罚分 %.0f，用时 %.1f 秒" % (result.状态, result.罚分, result.用时秒))
    for label, value in sorted(result.分项.items()):
        if value:
            print("  %-12s %8.0f" % (label, value))

    硬 = [x for x in result.连堂未满足 if x[2] == "硬"]
    if result.连堂未满足:
        print("\n连堂未满足 %d 条（其中硬约束 %d 条）" % (len(result.连堂未满足), len(硬)))
        for group, rule, strength in result.连堂未满足[:10]:
            print("  [%s] %-22s %s" % (strength, "·".join(map(str, group)), rule))
        if len(result.连堂未满足) > 10:
            print("  …… 其余见「问题清单」页")

    write_workbook(args.out, teams, result, cfg["时段"])
    print("\n已写入 %s" % args.out)
    sys.exit(0 if result.可行 else 2)


if __name__ == "__main__":
    main()
