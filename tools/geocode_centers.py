#!/usr/bin/env python3
"""把中心表里的地址批量转成经纬度，就地写回 config/centers.csv。

    python tools/geocode_centers.py                       # 默认 osm，不需要 key
    python tools/geocode_centers.py --provider amap --key <高德Key>   # 要更高精度时

只补「经度/纬度」两列为空的行；已经有坐标的默认不动（要重算加 --overwrite）。
每行会记下「坐标系」，因为 osm 给 WGS-84、amap 给 GCJ-02，差 300–700 米；
排班时会按这一列统一折算，所以两种混着用也不会算错。
地址列为空时用「城市 + 中心名」去查，查出来的地址会一并写回，方便你核对。
跑一次就够——结果是离线的，排班时不需要网络也不需要 key。
"""
import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from console import force_utf8   # noqa: E402
from engine.mapapi import MapError, make   # noqa: E402

FIELDS = ["中心", "校区", "区域", "地址", "经度", "纬度", "坐标系"]


def load(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        sys.exit("%s 里没有数据行" % path)
    missing = [c for c in ("中心", "经度", "纬度") if c not in rows[0]]
    if missing:
        sys.exit("中心表缺列：%s" % "、".join(missing))
    return rows


def save(path, rows):
    fields = list(dict.fromkeys(FIELDS + list(rows[0].keys())))
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    force_utf8()
    ap = argparse.ArgumentParser(description="批量把中心地址转成经纬度")
    ap.add_argument("--provider", default="osm",
                    help="osm = 开源服务，不要 key（默认）；amap = 高德，精度更好但要 key")
    ap.add_argument("--key", help="amap 才需要")
    ap.add_argument("--centers", default="config/centers.csv")
    ap.add_argument("--city", default="深圳")
    ap.add_argument("--overwrite", action="store_true", help="已有坐标的也重算")
    ap.add_argument("--dry-run", action="store_true", help="只打印，不写文件")
    args = ap.parse_args()

    rows = load(args.centers)
    try:
        client = make(args.provider, args.key, city=args.city)
    except MapError as e:
        sys.exit(str(e))
    print("用 %s，坐标系 %s\n" % (client.name, client.datum))

    done = skipped = failed = 0
    for row in rows:
        name = (row.get("中心") or "").strip()
        has_coords = (row.get("经度") or "").strip() and (row.get("纬度") or "").strip()
        if has_coords and not args.overwrite:
            skipped += 1
            continue

        address = (row.get("地址") or "").strip() or "%s%s" % (args.city, name)
        try:
            found = client.geocode(address)
        except MapError as e:
            print("  ✕ %-14s %s" % (name, e))
            failed += 1
            continue

        if not found:
            print("  ✕ %-14s 查不到「%s」——请在地址列填详细地址后重跑" % (name, address))
            failed += 1
            continue

        lon, lat = found
        row["经度"], row["纬度"] = "%.6f" % lon, "%.6f" % lat
        row["坐标系"] = client.datum
        if not (row.get("地址") or "").strip():
            row["地址"] = address
        print("  ✓ %-14s %.6f, %.6f" % (name, lon, lat))
        done += 1

    print("\n补全 %d 个，跳过 %d 个（已有坐标），失败 %d 个" % (done, skipped, failed))
    if args.dry_run:
        print("--dry-run，没有写文件")
    elif done:
        save(args.centers, rows)
        print("已写回 %s" % args.centers)
    if failed:
        print("\n失败的行请在地址列补详细街道地址再跑一次；")
        print("OSM 对国内商场/门店名覆盖有限，换 --provider amap --key <Key> 通常能查到。")
        sys.exit(1)


if __name__ == "__main__":
    main()
