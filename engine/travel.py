"""中心之间跑一趟要多久、多远，以及这趟跨中心能不能接受。

数据来源按可信度排队，前面有就不用后面的：
    ① config/travel.csv   地图 API 跑出来的真实驾车时间/里程（tools/travel_matrix.py）
    ② 经纬度直线估算       直线 km × 折算系数 ÷ 车速 + 固定开销
    ③ 同校区/同区域/跨区域  连坐标都没有时的兜底粗判

判定口径由配置的「判定方式」决定：
    时间 —— 排班给的赶路时间 ≥ 通行时间 + 安全余量
    距离 —— 两个中心的路程 ≤ 上限公里数
"""
import csv
import math
import os

from .coords import to_wgs84

FALLBACK_MINUTES = {"同校区": 15, "同区域": 40, "跨区域": 70}
FALLBACK_KM = {"同校区": 1.0, "同区域": 8.0, "跨区域": 20.0}
TRAVEL_FIELDS = ["from", "to", "minutes", "km", "source"]

BY_TIME = "时间"
BY_DISTANCE = "距离"


def haversine_km(lon1, lat1, lon2, lat2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def load_geo(cfg):
    """读坐标表和通行时间表。文件缺失就返回空，由 Travel 逐级退回。"""
    geo = cfg.get("地理", {}) or {}
    coords, table = {}, {}

    path = geo.get("中心坐标表")
    if path and os.path.exists(path):
        with open(path, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                lon, lat = (row.get("经度") or "").strip(), (row.get("纬度") or "").strip()
                if lon and lat:
                    # 各家坐标系不同（osm 给 WGS-84、amap 给 GCJ-02，差 300–700 米），
                    # 统一折算到 WGS-84 再存，混着用也不会算错
                    coords[row["中心"].strip()] = to_wgs84(
                        float(lon), float(lat), row.get("坐标系"))

    # 新键名「通行时间表」；「实测通行分钟」是旧名，继续认
    path = geo.get("通行时间表") or geo.get("实测通行分钟")
    if path and os.path.exists(path):
        with open(path, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                a, b = (row.get("from") or "").strip(), (row.get("to") or "").strip()
                if not a or not b:
                    continue
                try:
                    minutes = float(row["minutes"])
                except (KeyError, TypeError, ValueError):
                    continue
                try:
                    km = float(row.get("km") or "")
                except ValueError:
                    km = None
                entry = (minutes, km)
                table[(a, b)] = entry
                table.setdefault((b, a), entry)      # 单向数据也当双向用

    return coords, table


class Travel:
    def __init__(self, cfg, coords, table, campus_of, region_of):
        geo = cfg.get("地理", {}) or {}
        estimate = geo.get("估算") or geo          # 兼容旧的平铺写法

        self.coords = coords
        self.table = table
        self.campus_of = campus_of
        self.region_of = region_of

        self.detour = float(estimate.get("直线折算系数", 1.4))
        self.speed = float(estimate.get("平均车速_kmh", 22))
        self.overhead = float(estimate.get("固定开销_分钟", 15))

        self.mode = geo.get("判定方式", BY_TIME)
        self.margin = float((geo.get("时间") or {}).get("安全余量_分钟", 0))
        self.km_limit = (geo.get("距离") or {}).get("上限_km")
        self.km_limit = float(self.km_limit) if self.km_limit is not None else None

        self.used_fallback = False

    # ── 基础量 ────────────────────────────────────────────────────
    def tier(self, a, b):
        if self.campus_of.get(a) and self.campus_of.get(a) == self.campus_of.get(b):
            return "同校区"
        # 区域不明的一律按跨区域算。两个 None 相等就当成"同区域"的话，
        # 缺数据反而会放宽约束 —— 兜底应该保守，不该更松。
        ra, rb = self.region_of.get(a), self.region_of.get(b)
        if ra and rb and ra == rb:
            return "同区域"
        return "跨区域"

    def source(self, a, b):
        """这一对的数据是哪来的 —— 报告里要说清楚，免得把估算当实测。"""
        if a == b:
            return "同中心"
        if (a, b) in self.table:
            return "地图"
        if a in self.coords and b in self.coords:
            return "直线估算"
        return "粗判"

    def km(self, a, b):
        if a == b:
            return 0.0
        entry = self.table.get((a, b))
        if entry and entry[1] is not None:
            return entry[1]
        if a in self.coords and b in self.coords:
            return haversine_km(*self.coords[a], *self.coords[b]) * self.detour
        self.used_fallback = True
        return FALLBACK_KM[self.tier(a, b)]

    def minutes(self, a, b):
        if a == b:
            return 0.0
        entry = self.table.get((a, b))
        if entry:
            return entry[0]
        if a in self.coords and b in self.coords:
            km = haversine_km(*self.coords[a], *self.coords[b]) * self.detour
            return self.overhead + km / self.speed * 60
        self.used_fallback = True
        return FALLBACK_MINUTES[self.tier(a, b)]

    # ── 判定 ──────────────────────────────────────────────────────
    def acceptable(self, a, b, available_minutes):
        """这趟跨中心能不能接受。返回 (行不行, 说明)。

        按「判定方式」走：时间看赶路时间够不够，距离看路程超没超上限。
        """
        if a == b:
            return True, ""

        if self.mode == BY_DISTANCE:
            if self.km_limit is None:
                return True, ""
            km = self.km(a, b)
            if km <= self.km_limit:
                return True, ""
            return False, ("路程 %.1f km，超过上限 %.1f km（%s）"
                           % (km, self.km_limit, self.source(a, b)))

        need = self.minutes(a, b) + self.margin
        if available_minutes >= need:
            return True, ""
        return False, ("赶路只有 %d 分钟，需要约 %d 分钟%s（%s）"
                       % (available_minutes, round(need),
                          "（含 %d 分钟余量）" % self.margin if self.margin else "",
                          self.source(a, b)))

    def label(self, a, b):
        source = self.source(a, b)
        if source == "粗判":
            return "%s·粗判" % self.tier(a, b)
        return "%.1f km / %d 分钟·%s" % (self.km(a, b), round(self.minutes(a, b)), source)
