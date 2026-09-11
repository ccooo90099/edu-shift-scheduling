#!/usr/bin/env python3
"""排班体检 —— 按 config/rules.yaml 的口径检查一份现有排班，输出违规清单和基线分。

    python tools/health_check.py 排班明细.xlsx --config config/rules.yaml \
           [--sheet 名称] [--out 违规清单.csv]

排班和体检共用同一套配置和同一套权重，所以"排得好不好"始终是同一把尺子。
"""
import argparse
import csv
import math
import os
import statistics
import sys
from collections import defaultdict
from itertools import combinations

import pandas as pd
import yaml

TIME_COL = "首次服务时间"
FALLBACK_MINUTES = {"同校区": 15, "同区域": 40, "跨区域": 70}


# ── 基础工具 ──────────────────────────────────────────────────────────

def to_min(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def parse_slot(text):
    """'08:10-10:10' → (490, 610)"""
    a, b = text.split("-")
    return to_min(a), to_min(b)


def haversine_km(lon1, lat1, lon2, lat2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# ── 载入 ──────────────────────────────────────────────────────────────

def load_config(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_schedule(path, cfg, sheet=None):
    df = pd.read_excel(path, sheet_name=sheet if sheet else 0)
    df = df.map(lambda v: v.strip() if isinstance(v, str) else v)

    campus = cfg.get("校区", {})
    if campus.get("由中心推导", True):
        keep = set(campus.get("不合并") or [])
        suffixes = campus.get("合并后缀") or []
        pattern = "(" + "|".join(suffixes) + ")$" if suffixes else None

        def to_campus(name):
            if name in keep or not pattern:
                return name
            import re
            return re.sub(pattern, "", name)

        df["校区"] = df["中心"].map(to_campus)
    elif "校区" not in df.columns:
        df["校区"] = df["中心"]

    if "团队名称" in df.columns:
        df["班序"] = df["团队名称"].astype(str).str.extract(r"(\d+)$")

    df[["_start", "_end"]] = df[TIME_COL].apply(lambda t: pd.Series(parse_slot(t)))
    return df


def load_geo(cfg):
    """返回 (坐标表, 实测通行分钟表)。文件缺失就返回空，调用方退回粗判。"""
    geo = cfg.get("地理", {}) or {}
    coords, explicit = {}, {}

    path = geo.get("中心坐标表")
    if path and os.path.exists(path):
        with open(path, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                lon, lat = (row.get("经度") or "").strip(), (row.get("纬度") or "").strip()
                if lon and lat:
                    coords[row["中心"].strip()] = (float(lon), float(lat))

    path = geo.get("实测通行分钟")
    if path and os.path.exists(path):
        with open(path, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                a, b = row["from"].strip(), row["to"].strip()
                explicit[(a, b)] = explicit[(b, a)] = float(row["minutes"])

    return coords, explicit


# ── 通行时间 ──────────────────────────────────────────────────────────

class Travel:
    """A→B 需要多少分钟。优先实测表，其次经纬度估算，最后退回三档粗判。"""

    def __init__(self, cfg, coords, explicit, campus_of, region_of):
        geo = cfg.get("地理", {}) or {}
        self.coords = coords
        self.explicit = explicit
        self.campus_of = campus_of
        self.region_of = region_of
        self.detour = float(geo.get("直线折算系数", 1.4))
        self.speed = float(geo.get("平均车速_kmh", 22))
        self.overhead = float(geo.get("固定开销_分钟", 15))
        self.used_fallback = False

    def km(self, a, b):
        if a in self.coords and b in self.coords:
            lon1, lat1 = self.coords[a]
            lon2, lat2 = self.coords[b]
            return haversine_km(lon1, lat1, lon2, lat2) * self.detour
        return None

    def minutes(self, a, b):
        if a == b:
            return 0.0
        if (a, b) in self.explicit:
            return self.explicit[(a, b)]
        km = self.km(a, b)
        if km is not None:
            return self.overhead + km / self.speed * 60
        self.used_fallback = True
        if self.campus_of.get(a) == self.campus_of.get(b):
            return FALLBACK_MINUTES["同校区"]
        if self.region_of.get(a) == self.region_of.get(b):
            return FALLBACK_MINUTES["同区域"]
        return FALLBACK_MINUTES["跨区域"]

    def label(self, a, b):
        km = self.km(a, b)
        if km is not None:
            return "%.1f km" % km
        if self.campus_of.get(a) == self.campus_of.get(b):
            return "同校区·估"
        if self.region_of.get(a) == self.region_of.get(b):
            return "同区域·估"
        return "跨区域·估"


# ── 检查项 ────────────────────────────────────────────────────────────

def overlaps(a, b):
    return a[0] < b[1] and b[0] < a[1]


def check_teacher_clash(df, add):
    """H1 一个老师同一时间不能在两个团队。"""
    n = 0
    for key, sub in df.groupby(["段次", "周", "主指导员"]):
        rows = sub.to_dict("records")
        for x, y in combinations(rows, 2):
            if overlaps((x["_start"], x["_end"]), (y["_start"], y["_end"])):
                n += 1
                add("H1", "老师同时段撞车", "%s %s %s" % key,
                    "%s @%s 与 %s @%s" % (x["中心"], x[TIME_COL], y["中心"], y[TIME_COL]))
    return n


def check_product_clash(df, cfg, add):
    """H2 同时段 + 同一撮学生 里不能出现两个不同产品。"""
    keys = cfg["冲突口径"]["分组字段"]
    missing = [k for k in keys if k not in df.columns]
    if missing:
        sys.exit("配置里的分组字段在表中不存在：%s" % "、".join(missing))

    pairs = 0
    dirty = set()
    for key, sub in df.groupby(["段次", "周"] + keys):
        rows = sub.to_dict("records")
        for x, y in combinations(rows, 2):
            if x["产品"] != y["产品"] and overlaps((x["_start"], x["_end"]), (y["_start"], y["_end"])):
                pairs += 1
                dirty.add(x["团队ID"])
                dirty.add(y["团队ID"])
                add("H2", "同撮学生同时段排了两个产品", "·".join(map(str, key)),
                    "%s %s(%s) ✕ %s %s(%s)" % (x[TIME_COL], x["产品"], x["主指导员"],
                                               y[TIME_COL], y["产品"], y["主指导员"]))
    return pairs, len(dirty)


def check_room_clash(df, add):
    """H3 同一间教室同一时间只能有一个团队。"""
    if "指导室" not in df.columns:
        return 0
    n = 0
    sub = df[df["指导室"].astype(str).str.strip() != ""]
    for key, g in sub.groupby(["段次", "周", "中心", "指导室"]):
        rows = g.to_dict("records")
        for x, y in combinations(rows, 2):
            if overlaps((x["_start"], x["_end"]), (y["_start"], y["_end"])):
                n += 1
                add("H3", "教室同时段撞车", "·".join(map(str, key)),
                    "%s ✕ %s" % (x[TIME_COL], y[TIME_COL]))
    return n


def build_adjacency(slots):
    """两个时段"相接" = 中间塞不下任何一个别的时段。"""
    parsed = sorted((parse_slot(s) for s in slots))

    def gap_count(a, b):
        return sum(1 for s in parsed if a[1] <= s[0] and s[1] <= b[0])

    return parsed, gap_count


def check_adjacency(df, cfg, add):
    """S1 配置里要求连堂的产品，必须占前后相接的时段。"""
    rules = (cfg.get("连堂", {}) or {}).get("规则") or []
    scope = (cfg.get("连堂", {}) or {}).get("分组范围") or ["校区", "程度", "团队类型"]
    _, gap_count = build_adjacency(cfg["时段"])

    stats = []
    for rule in rules:
        products = rule["产品"]
        allowed = int(rule.get("允许中间隔", 0))
        limit = rule.get("最大间隙_分钟")
        ordered = rule.get("顺序") == "按列表"
        total = ok = tight_ok = 0
        for key, sub in df.groupby(["段次", "周"] + scope):
            picks = {p: sub[sub["产品"] == p] for p in products}
            if any(v.empty for v in picks.values()):
                continue
            for a, b in combinations(products, 2):
                # 同一撮学生里，取每个产品最早的那一节来判断
                x = picks[a].nsmallest(1, "_start").iloc[0]
                y = picks[b].nsmallest(1, "_start").iloc[0]
                first, second = (x, y) if x["_start"] <= y["_start"] else (y, x)
                total += 1
                if overlaps((x["_start"], x["_end"]), (y["_start"], y["_end"])):
                    add("S1", "%s · 两节撞在同一时段" % rule["名称"], "·".join(map(str, key)),
                        "%s %s ✕ %s %s" % (a, x[TIME_COL], b, y[TIME_COL]))
                    continue
                between = gap_count((first["_start"], first["_end"]), (second["_start"], second["_end"]))
                wait = second["_start"] - first["_end"]
                order_ok = (not ordered) or first["产品"] == products[0]
                no_class_between = between <= allowed and order_ok
                if no_class_between:
                    ok += 1
                    if limit is None or wait <= limit:
                        tight_ok += 1
                    else:
                        add("S1", "%s · 中间等 %d 分钟（超过 %d）" % (rule["名称"], wait, limit),
                            "·".join(map(str, key)),
                            "%s %s → %s %s" % (first["产品"], first[TIME_COL],
                                               second["产品"], second[TIME_COL]))
                else:
                    add("S1", "%s · 没挨着（中间夹了 %d 节别的课）" % (rule["名称"], between),
                        "·".join(map(str, key)),
                        "%s %s → %s %s" % (first["产品"], first[TIME_COL], second["产品"], second[TIME_COL]))
        stats.append((rule["名称"], rule.get("强度", "软"), total, ok, tight_ok, limit))
    return stats


def check_transfers(df, travel, cfg, add):
    """S2/S3 老师跨中心跑场：次数、路程、以及赶路时间够不够。"""
    hard = (cfg.get("地理", {}) or {}).get("转场硬上限_分钟")
    days = moves = tight = 0
    single = 0
    km_total = 0.0
    gaps = []

    for key, sub in df.groupby(["段次", "周", "主指导员"]):
        days += 1
        sub = sub.sort_values("_start")
        rows = sub.to_dict("records")
        if sub["中心"].nunique() == 1:
            single += 1
        for prev, cur in zip(rows, rows[1:]):
            if prev["中心"] != cur["中心"]:
                moves += 1
                need = travel.minutes(prev["中心"], cur["中心"])
                have = cur["_start"] - prev["_end"]
                km = travel.km(prev["中心"], cur["中心"])
                if km:
                    km_total += km
                if have < need:
                    tight += 1
                    level = "H3-地理" if hard and have < hard else "S3"
                    add(level, "赶路时间不够（有 %d 分钟，需要约 %d 分钟）" % (have, need),
                        "%s %s %s" % key,
                        "%s %s → %s %s（%s）" % (prev["中心"], prev[TIME_COL],
                                                cur["中心"], cur[TIME_COL],
                                                travel.label(prev["中心"], cur["中心"])))
        slots = sorted({(r["_start"], r["_end"]) for r in rows})
        if len(slots) > 1:
            _, gap_count = build_adjacency(cfg["时段"])
            gaps.append(sum(gap_count(a, b) for a, b in zip(slots, slots[1:])))

    return dict(days=days, single=single, moves=moves, tight=tight,
                km=km_total, gaps=gaps)


# ── 打分与报告 ────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="排班体检")
    ap.add_argument("schedule", help="排班明细 xlsx")
    ap.add_argument("--config", default="config/rules.yaml")
    ap.add_argument("--sheet", default=None)
    ap.add_argument("--out", default=None, help="把违规明细写成 csv")
    args = ap.parse_args()

    cfg = load_config(args.config)
    df = load_schedule(args.schedule, cfg, args.sheet)

    findings = []

    def add(code, what, where, detail):
        findings.append(dict(级别=code, 问题=what, 位置=where, 明细=detail))

    campus_of = dict(zip(df["中心"], df["校区"]))
    region_of = dict(zip(df["中心"], df["区域"])) if "区域" in df.columns else {}
    coords, explicit = load_geo(cfg)
    travel = Travel(cfg, coords, explicit, campus_of, region_of)

    print("排班体检 · %s" % os.path.basename(args.schedule))
    print("=" * 66)
    print("%d 个团队 | %d 中心 / %d 校区 | %d 位指导员 | 口径：同时段 + %s"
          % (len(df), df["中心"].nunique(), df["校区"].nunique(),
             df["主指导员"].nunique(), " + ".join(cfg["冲突口径"]["分组字段"])))

    h1 = check_teacher_clash(df, add)
    h2_pairs, h2_teams = check_product_clash(df, cfg, add)
    h3 = check_room_clash(df, add)
    s1 = check_adjacency(df, cfg, add)
    tr = check_transfers(df, travel, cfg, add)

    print("\n硬约束")
    print("  H1 老师同时段撞车     %s" % ("✓ 0" if not h1 else "✕ %d 处" % h1))
    print("  H2 同撮学生撞产品     %s   （%d 对撞车，涉及 %d / %d 个团队，%.0f%%）"
          % ("✓ 0" if not h2_teams else "✕", h2_pairs, h2_teams, len(df),
             100 * h2_teams / max(len(df), 1)))
    print("  H3 教室同时段撞车     %s" % ("✓ 0" if not h3 else "✕ %d 处" % h3))

    print("\n连堂（S1）")
    for name, strength, total, ok, tight_ok, limit in s1:
        line = "  %-14s [%s]  中间不夹别的课 %d/%d（%.0f%%）" % (
            name, strength, ok, total, 100 * ok / max(total, 1))
        if limit is not None:
            line += "；其中等待 ≤%d 分钟的 %d（%.0f%%）" % (
                limit, tight_ok, 100 * tight_ok / max(total, 1))
        print(line)

    print("\n老师跑场（S2 / S3）")
    print("  当日排班 %d 人次，其中 %d 人次只在一个中心（%.0f%%）"
          % (tr["days"], tr["single"], 100 * tr["single"] / max(tr["days"], 1)))
    print("  跨中心转场 %d 次，赶路时间不够的 %d 次" % (tr["moves"], tr["tight"]))
    if travel.coords:
        print("  转场总里程约 %.0f km，平均每次 %.1f km"
              % (tr["km"], tr["km"] / max(tr["moves"], 1)))
    if travel.used_fallback:
        print("  ⚠ 部分中心缺经纬度，已退回「同校区/同区域/跨区域」粗判。")
        print("    填好 %s 的经度/纬度两列即可按真实距离计算。"
              % (cfg.get("地理", {}) or {}).get("中心坐标表", "config/centers.csv"))
    if tr["gaps"]:
        print("  课表空档合计 %d 段，有空档的 %d/%d 人次"
              % (sum(tr["gaps"]), sum(1 for g in tr["gaps"] if g), len(tr["gaps"])))

    load = df.groupby("主指导员").size()
    w = cfg["权重"]
    adj_miss = sum(total - tight_ok for _, _, total, _, tight_ok, _ in s1)
    score = (w["连堂不相邻"] * adj_miss
             + w["转场时间不够"] * tr["tight"]
             + w["每公里转场"] * tr["km"]
             + w["跨中心一次"] * tr["moves"]
             + w["课表空档一段"] * sum(tr["gaps"])
             + w["工作量方差"] * (statistics.pvariance(load) if len(load) > 1 else 0))
    print("\n工作量：人均 %.1f 个团队，最多 %d 个，方差 %.1f"
          % (load.mean(), load.max(), statistics.pvariance(load) if len(load) > 1 else 0))
    print("\n罚分合计 %.0f   （硬约束违规 %d 处，不计入分数——它们是不可行，不是扣分）"
          % (score, h1 + h2_pairs + h3))

    if args.out:
        with open(args.out, "w", newline="", encoding="utf-8-sig") as f:
            wr = csv.DictWriter(f, fieldnames=["级别", "问题", "位置", "明细"])
            wr.writeheader()
            wr.writerows(findings)
        print("\n违规明细 %d 条 → %s" % (len(findings), args.out))
    else:
        print("\n违规明细 %d 条（加 --out xxx.csv 导出）" % len(findings))


if __name__ == "__main__":
    main()
