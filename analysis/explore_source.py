#!/usr/bin/env python3
"""排班源表探查脚本 —— docs/需求理解.md 里引用的所有数字都由本脚本产出。

用法:
    python analysis/explore_source.py <排班明细.xlsx> [sheet名]

输入是"排完之后"的明细表，一行一个团队，需要包含以下列:
    区域 中心 段次 周 首次服务时间 程度 产品 团队类型 主指导员 团队ID 指导室
"""
import sys
from itertools import combinations

import pandas as pd

TIME_ORDER = [
    "08:10-10:10", "10:30-12:30", "13:30-15:30",
    "14:00-16:00", "16:20-18:20", "18:30-20:30",
]
TIME_COL = "首次服务时间"


def load(path, sheet=0):
    df = pd.read_excel(path, sheet_name=sheet)
    df = df.map(lambda v: v.strip() if isinstance(v, str) else v)
    # 中心带"科学/文学"后缀的其实是同一个校区的两栋楼，冲突判定要按校区
    df["校区"] = df["中心"].str.replace(r"(科学|文学)$", "", regex=True)
    df["班序"] = df["团队名称"].str.extract(r"(\d+)$")
    df["slot"] = df[TIME_COL].map({t: i for i, t in enumerate(TIME_ORDER)})
    # 在读人数：导出表里没有这一列，用购买时长反算
    df["人数"] = df["购买服务时长分钟数"] / (df["团队分钟数"] * df["本团队服务次数"])
    return df


def rule1_violations(df):
    """规则1「同时段+同校区+同程度+不同产品 不能同排」在四种粒度下的违反情况。"""
    variants = {
        "校区+程度（原话，最严）": ["段次", "周", TIME_COL, "校区", "程度"],
        "中心+程度": ["段次", "周", TIME_COL, "中心", "程度"],
        "校区+程度+团队类型": ["段次", "周", TIME_COL, "校区", "程度", "团队类型"],
        "校区+程度+团队类型+班序": ["段次", "周", TIME_COL, "校区", "程度", "团队类型", "班序"],
    }
    print("### 规则1 违反情况（不同粒度口径）")
    for name, keys in variants.items():
        g = df.groupby(keys)["产品"].agg(["nunique", "count"])
        bad = g[g["nunique"] > 1]
        print("  %-24s 组数=%-4d 违反=%-4d (%2.0f%%) 涉及团队=%d"
              % (name, len(g), len(bad), 100 * len(bad) / len(g), bad["count"].sum()))


def adjacency(df):
    """同一学生群（校区+程度+团队类型）内，产品两两之间的时段间隔。"""
    same = adj = far = 0
    for _, sub in df.groupby(["段次", "周", "校区", "程度", "团队类型"]):
        first = sub.groupby("产品")["slot"].min()
        for a, b in combinations(sorted(first.index), 2):
            d = abs(first[a] - first[b])
            same += d == 0
            adj += d == 1
            far += d > 1
    total = same + adj + far
    print("\n### 捆绑相邻（S1）基线")
    print("  同群产品对 %d | 撞同一时段 %d (%.0f%%) | 相邻 %d (%.0f%%) | 隔开 %d (%.0f%%)"
          % (total, same, 100 * same / total, adj, 100 * adj / total, far, 100 * far / total))


def instructor_travel(df):
    """老师当日的跨中心/跨区域情况。"""
    g = df.groupby(["段次", "周", "主指导员"]).agg(
        中心数=("中心", "nunique"), 区域数=("区域", "nunique"), 团队数=("团队ID", "count"))
    print("\n### 老师转场（S2/S3）基线")
    print("  当日排班 %d 人次 | 只在1个中心 %d (%.0f%%) | 跨2中心 %d | 跨3中心 %d | 跨区域 %d (%.0f%%)"
          % (len(g), (g["中心数"] == 1).sum(), 100 * (g["中心数"] == 1).mean(),
             (g["中心数"] == 2).sum(), (g["中心数"] == 3).sum(),
             (g["区域数"] > 1).sum(), 100 * (g["区域数"] > 1).mean()))

    moves = []
    for key, sub in df.groupby(["段次", "周", "主指导员"]):
        if sub["中心"].nunique() == 1:
            continue
        prev = None
        for _, row in sub.sort_values("slot").iterrows():
            if prev is not None and prev["中心"] != row["中心"]:
                moves.append((row["slot"] - prev["slot"],
                              prev["校区"] == row["校区"], prev["区域"] == row["区域"]))
            prev = row
    mv = pd.DataFrame(moves, columns=["间隔段数", "同校区", "同区域"])
    print("  跨中心转场 %d 次 | 背靠背(隔1段) %d 次 | 同校区转场 %d | 同区域转场 %d"
          % (len(mv), (mv["间隔段数"] == 1).sum(), mv["同校区"].sum(), mv["同区域"].sum()))

    gaps = []
    for _, sub in df.groupby(["段次", "周", "主指导员"]):
        s = sorted(sub["slot"].unique())
        if len(s) > 1:
            gaps.append(s[-1] - s[0] + 1 - len(s))
    print("  多节课人次 %d | 有空档 %d | 空档总段数 %d" % (len(gaps), sum(1 for g_ in gaps if g_), sum(gaps)))


def hard_checks(df):
    print("\n### 硬约束现状")
    g = df.groupby(["段次", "周", TIME_COL, "主指导员"])["团队ID"].count()
    print("  H1 老师同时段撞车: %d 组" % (g > 1).sum())
    room = df[df["指导室"] != ""]
    g = room.groupby(["段次", "周", TIME_COL, "中心", "指导室"])["团队ID"].count()
    print("  H3 教室同时段撞车: %d 组（有教室数据 %d/%d 行）" % ((g > 1).sum(), len(room), len(df)))
    prod = df.groupby("主指导员")["产品"].nunique()
    print("  H4 跨产品授课的老师: %d / %d 人" % ((prod > 1).sum(), len(prod)))


def shape(df):
    print("### 规模")
    print("  %d 行 | %d 中心 / %d 校区 | %d 产品 | %d 老师 | %d 时段"
          % (len(df), df["中心"].nunique(), df["校区"].nunique(),
             df["产品"].nunique(), df["主指导员"].nunique(), df[TIME_COL].nunique()))
    print(df.groupby("段次").agg(团队数=("团队ID", "count"), 中心数=("中心", "nunique"),
                                老师数=("主指导员", "nunique"), 时段数=(TIME_COL, "nunique")).to_string())
    print("  在读人数: 均值 %.1f / 容量 %.0f，%.0f%% 可整除"
          % (df["人数"].mean(), df["服务容量"].mean(), 100 * (df["人数"] % 1 == 0).mean()))
    print()


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    sheet = sys.argv[2] if len(sys.argv) > 2 else 0
    df = load(sys.argv[1], sheet)
    shape(df)
    rule1_violations(df)
    adjacency(df)
    instructor_travel(df)
    hard_checks(df)


if __name__ == "__main__":
    main()
