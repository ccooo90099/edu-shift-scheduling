#!/usr/bin/env python3
"""排班体检（命令行）—— 引擎在 engine/health.py，这里只负责打印和导出。

    python tools/health_check.py 排班明细.xlsx --config config/rules.yaml \
           [--sheet 名称] [--out 违规清单.csv]
"""
import argparse
import csv
import os
import sys
from dataclasses import asdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from console import force_utf8
except ImportError:          # console.py 缺失时也不该崩 —— 它只是 6 行标准库
    def force_utf8():
        for _stream in (sys.stdout, sys.stderr):
            try:
                _stream.reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, ValueError, OSError):
                pass
from engine import load_config, run   # noqa: E402


def render(rep, name):
    out = []
    add = out.append
    add("排班体检 · %s" % name)
    add("=" * 66)
    add("%d 个团队 | %d 中心 / %d 校区 | %d 位指导员 | 口径：%s"
        % (rep.团队数, rep.中心数, rep.校区数, rep.指导员数, rep.冲突口径))

    if rep.未排上行数:
        add("  ⚠ 另有 %d 个团队没有时段（没排上），不参与下面的判定" % rep.未排上行数)
    add("\n硬约束")
    add("  H1 老师同时段撞车     %s" % ("✓ 0" if not rep.老师撞车 else "✕ %d 处" % rep.老师撞车))
    add("  H2 同撮学生撞产品     %s   （%d 对撞车，涉及 %d / %d 个团队，%.0f%%）"
        % ("✓ 0" if not rep.产品撞车团队数 else "✕", rep.产品撞车对数,
           rep.产品撞车团队数, rep.团队数, 100 * rep.产品撞车团队数 / max(rep.团队数, 1)))
    add("  H3 教室同时段撞车     %s" % ("✓ 0" if not rep.教室撞车 else "✕ %d 处" % rep.教室撞车))

    add("\n连堂（S1）")
    if rep.间隔阈值说明:
        add("  间隔阈值（自动推算）：%s" % rep.间隔阈值说明)
    for name_, strength, total, loose, tight, limit in rep.连堂:
        line = "  %-14s [%s]  中间不夹别的课 %d/%d（%.0f%%）" % (
            name_, strength, loose, total, 100 * loose / max(total, 1))
        if limit is not None:
            line += "；其中等待 ≤%d 分钟的 %d（%.0f%%）" % (
                limit, tight, 100 * tight / max(total, 1))
        add(line)

    add("\n老师跑场（S2 / S3）")
    add("  当日排班 %d 人次，其中 %d 人次只在一个中心（%.0f%%）"
        % (rep.当日人次, rep.单中心人次, 100 * rep.单中心人次 / max(rep.当日人次, 1)))
    add("  跨中心转场 %d 次，按「%s」判定不可接受的 %d 次"
        % (rep.转场次数, rep.判定方式, rep.赶不及次数))
    if rep.转场里程:
        add("  转场总里程约 %.0f km，平均每次 %.1f km"
            % (rep.转场里程, rep.转场里程 / max(rep.转场次数, 1)))
    if rep.转场按来源:
        add("  数据来源：%s" % "，".join(
            "%s %d 次" % (k, v) for k, v in sorted(rep.转场按来源.items())))
    if rep.用了粗判:
        add("  ⚠ 部分中心没有坐标，这些只能按「同校区/同区域/跨区域」粗判。")
        add("    跑 tools/geocode_centers.py 补坐标，再跑 tools/travel_matrix.py 出真实驾车时间。")
    add("  课表空档合计 %d 段，有空档的 %d/%d 人次"
        % (rep.空档段数, rep.有空档人次, rep.多节课人次))

    add("\n工作量：人均 %.1f 个团队，最多 %d 个，方差 %.1f"
        % (rep.人均团队, rep.最多团队, rep.工作量方差))
    add("\n罚分合计 %.0f   （硬约束违规 %d 处，不计入分数——它们是不可行，不是扣分）"
        % (rep.罚分, rep.硬约束违规))
    return "\n".join(out)


def main():
    force_utf8()
    ap = argparse.ArgumentParser(description="排班体检")
    ap.add_argument("schedule", help="排班明细 xlsx")
    ap.add_argument("--config", default="config/rules.yaml")
    ap.add_argument("--sheet", default=None)
    ap.add_argument("--out", default=None, help="把违规明细写成 csv")
    args = ap.parse_args()

    cfg = load_config(args.config)
    rep = run(args.schedule, cfg, args.sheet)
    print(render(rep, os.path.basename(args.schedule)))

    if args.out:
        with open(args.out, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=["级别", "问题", "位置", "明细"])
            w.writeheader()
            w.writerows(asdict(x) for x in rep.findings)
        print("\n违规明细 %d 条 → %s" % (len(rep.findings), args.out))
    else:
        print("\n违规明细 %d 条（加 --out xxx.csv 导出）" % len(rep.findings))

    sys.exit(0 if rep.可行 else 2)


if __name__ == "__main__":
    main()
