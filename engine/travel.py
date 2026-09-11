"""中心之间要跑多久 —— 按地图算，不是按行政区粗分。

优先级：实测通行时间表 > 经纬度估算 > 同校区/同区域/跨区域三档兜底。
"""
import csv
import math
import os

FALLBACK_MINUTES = {"同校区": 15, "同区域": 40, "跨区域": 70}


def haversine_km(lon1, lat1, lon2, lat2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def load_geo(cfg):
    """读坐标表和实测通行表。文件缺失返回空，由 Travel 退回粗判。"""
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


class Travel:
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
            return haversine_km(*self.coords[a], *self.coords[b]) * self.detour
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
