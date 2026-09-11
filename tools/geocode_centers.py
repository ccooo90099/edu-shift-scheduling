#!/usr/bin/env python3
"""把中心表里的地址批量转成经纬度，就地写回 config/centers.csv。

    python tools/geocode_centers.py                       # 默认 osm，不需要 key
    python tools/geocode_centers.py --provider amap --key <高德Key>   # 要更高精度时

只补「经度/纬度」两列为空的行；已经有坐标的默认不动（要重算加 --overwrite）。

"百花科学""石厦文学"是内部中心名，地图上没有这个 POI，直接查必然落空。
所以每个中心按由细到粗试几种问法，命中就停：

    ① 地址列填的详细地址
    ② 城市 + 中心名          深圳百花科学
    ③ 城市 + 区域 + 校区名    深圳福田区百花
    ④ 城市 + 校区名          深圳百花        ← 校区名通常是真实地名，命中率最高

同校区的几个中心（百花科学/百花文学是同一个校区的两栋楼）会共用查询结果，
少调用几次，也保证它们坐标一致。命中的问法写进「定位依据」列，方便你核对。

查出来的点会做一次范围校验：落到城市范围外的直接丢弃 —— 地图服务对模糊
查询经常返回外省的同名地点，混进来会把全城距离算歪，而且不会报错。

坐标系也会记下来：osm 给 WGS-84、amap 给 GCJ-02，差 300–700 米，
排班时按这一列统一折算，所以两种混着用不会算错。
地址列为空时用「城市 + 中心名」去查，查出来的地址会一并写回，方便你核对。
跑一次就够——结果是离线的，排班时不需要网络也不需要 key。
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

FIELDS = ["中心", "校区", "区域", "地址", "经度", "纬度", "坐标系", "定位依据"]

# 深圳市域大致范围。查出来的点落在外面就是查错了，宁可留空也不要写错的坐标
CITY_BOUNDS = {"深圳": (113.70, 114.70, 22.35, 22.95)}
DEFAULT_BOUNDS = (73.0, 136.0, 3.0, 54.0)      # 兜底：国境范围


def in_bounds(lon, lat, city):
    west, east, south, north = CITY_BOUNDS.get(city, DEFAULT_BOUNDS)
    return west <= lon <= east and south <= lat <= north


def queries(row, city):
    """由细到粗的几种问法，去重后按顺序试。"""
    name = (row.get("中心") or "").strip()
    campus = (row.get("校区") or "").strip()
    region = (row.get("区域") or "").strip()
    address = (row.get("地址") or "").strip()

    out = []
    for q in (address,
              "%s%s" % (city, name) if name else "",
              "%s%s%s" % (city, region, campus) if campus and region else "",
              "%s%s" % (city, campus) if campus else ""):
        if q and q not in out:
            out.append(q)
    return out


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

    cache = {}          # 问法 → 结果，同校区的中心直接复用，少调几次
    done = skipped = failed = 0
    rejected = []

    for row in rows:
        name = (row.get("中心") or "").strip()
        has_coords = (row.get("经度") or "").strip() and (row.get("纬度") or "").strip()
        if has_coords and not args.overwrite:
            skipped += 1
            continue

        hit = None
        for query in queries(row, args.city):
            if query in cache:
                found = cache[query]
            else:
                try:
                    found = client.geocode(query)
                except MapError as e:
                    print("  ✕ %-14s %s" % (name, e))
                    found = None
                    break
                if found and not in_bounds(found[0], found[1], args.city):
                    rejected.append((name, query, found))
                    found = None
                cache[query] = found
            if found:
                hit = (query, found)
                break

        if not hit:
            print("  ✕ %-14s 几种问法都没查到" % name)
            failed += 1
            continue

        query, (lon, lat) = hit
        row["经度"], row["纬度"] = "%.6f" % lon, "%.6f" % lat
        row["坐标系"] = client.datum
        row["定位依据"] = query
        print("  ✓ %-14s %.6f, %.6f   ← %s" % (name, lon, lat, query))
        done += 1

    print("\n补全 %d 个，跳过 %d 个（已有坐标），失败 %d 个，调用 %d 次"
          % (done, skipped, failed, len(cache)))
    if rejected:
        print("\n丢弃了 %d 个落在%s范围外的结果（大概率是外地同名地点）：" % (len(rejected), args.city))
        for name, query, (lon, lat) in rejected:
            print("  %-14s 「%s」→ %.4f, %.4f" % (name, query, lon, lat))
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
