#!/usr/bin/env python3
"""算出任意两个中心之间的驾车时间和里程，存成 config/travel.csv。

    python tools/travel_matrix.py                         # 默认 osm，不需要 key
    python tools/travel_matrix.py --provider amap --key <高德Key>

跑一次就够。排班时只读这张表，完全离线，不需要网络也不需要 key。
osm 走 OSRM 的 table 接口，一次调用出整个矩阵；amap 是 N 次（每次一个终点）。
"""
import argparse
import csv
import os
import sys

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
from engine.mapapi import MapError, make   # noqa: E402
from engine.travel import TRAVEL_FIELDS   # noqa: E402


def load_centers(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    centers = []
    for row in rows:
        lon, lat = (row.get("经度") or "").strip(), (row.get("纬度") or "").strip()
        if lon and lat:
            centers.append((row["中心"].strip(), float(lon), float(lat)))
    if len(centers) < 2:
        sys.exit("有坐标的中心不足 2 个。先跑 tools/geocode_centers.py 把经纬度补齐。")
    missing = len(rows) - len(centers)
    if missing:
        print("⚠ 有 %d 个中心还没有坐标，本次跳过。" % missing)
    return centers


def collect_matrix(client, centers):
    """一次调用拿到整个矩阵（OSRM）。"""
    names = [n for n, _, _ in centers]
    try:
        minutes, km = client.matrix([(x, y) for _, x, y in centers])
    except MapError as e:
        print("  ✕ %s" % e)
        return [], len(names) * (len(names) - 1)

    pairs, failed = [], 0
    for i, a in enumerate(names):
        for j, b in enumerate(names):
            if i == j:
                continue
            value, distance = minutes[i][j], km[i][j]
            if value is None or distance is None:
                failed += 1
                continue
            pairs.append({"from": a, "to": b, "minutes": "%.1f" % value,
                          "km": "%.2f" % distance, "source": client.name})
    print("  ✓ %d/%d 对" % (len(pairs), len(names) * (len(names) - 1)))
    return pairs, failed


def collect_pairwise(client, centers):
    """一个终点一次调用（高德）。"""
    pairs, failed = [], 0
    for name, lon, lat in centers:
        others = [(n, x, y) for n, x, y in centers if n != name]
        try:
            results = client.driving([(x, y) for _, x, y in others], (lon, lat))
        except MapError as e:
            print("  ✕ 到「%s」：%s" % (name, e))
            failed += len(others)
            continue
        ok = 0
        for (other, _, _), value in zip(others, results):
            if value is None:
                failed += 1
                continue
            minutes, km = value
            pairs.append({"from": other, "to": name, "minutes": "%.1f" % minutes,
                          "km": "%.2f" % km, "source": client.name})
            ok += 1
        print("  ✓ 到「%s」：%d/%d" % (name, ok, len(others)))
    return pairs, failed


def main():
    force_utf8()
    ap = argparse.ArgumentParser(description="生成中心之间的驾车时间/里程表")
    ap.add_argument("--provider", default="osm",
                    help="osm = 开源服务，不要 key（默认）；amap = 高德，要 key")
    ap.add_argument("--key", help="amap 才需要")
    ap.add_argument("--centers", default="config/centers.csv")
    ap.add_argument("--out", default="config/travel.csv")
    ap.add_argument("--dry-run", action="store_true", help="只打印，不写文件")
    args = ap.parse_args()

    # 先验 key，再读文件 —— 缺 key 就没必要白读一遍中心表
    try:
        client = make(args.provider, args.key)
    except MapError as e:
        sys.exit(str(e))
    centers = load_centers(args.centers)

    total = len(centers) * (len(centers) - 1)
    one_shot = hasattr(client, "matrix")
    print("%d 个中心，共 %d 对，用 %s（%s）…\n"
          % (len(centers), total, client.name,
             "一次调用出整个矩阵" if one_shot else "%d 次调用" % len(centers)))

    pairs, failed = (collect_matrix if one_shot else collect_pairwise)(client, centers)
    print("\n算出 %d 对，失败 %d 对" % (len(pairs), failed))
    if not pairs:
        sys.exit("一对都没算出来，检查 Key 和网络。")

    if args.dry_run:
        print("--dry-run，没有写文件")
        return
    with open(args.out, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=TRAVEL_FIELDS)
        writer.writeheader()
        writer.writerows(pairs)
    print("已写入 %s —— 排班从此不用联网。" % args.out)


if __name__ == "__main__":
    main()
