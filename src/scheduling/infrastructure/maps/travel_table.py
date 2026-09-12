"""通行时间的查询实现。

数据来源按可信度排队，前面有就不用后面的：

    ① travel.csv   地图 API 跑出来的真实驾车时间/里程
    ② 经纬度直线估算  直线 km × 折算系数 ÷ 车速 + 固定开销
    ③ 档位兜底      同校区 / 同区域 / 跨区域

**报告里必须标注用的是哪一档**，免得把估算当实测看。
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from ...domain.model.venue import Center
from ...domain.policy.travel import (
    ProximityTier, TravelEstimate, TravelSource, proximity_tier)
from .datum import haversine_km

TRAVEL_FIELDS = ["from", "to", "minutes", "km", "source"]

FALLBACK_MINUTES = {ProximityTier.SAME_CAMPUS: 15,
                    ProximityTier.SAME_REGION: 40,
                    ProximityTier.CROSS_REGION: 70}
FALLBACK_KM = {ProximityTier.SAME_CAMPUS: 1.0,
               ProximityTier.SAME_REGION: 8.0,
               ProximityTier.CROSS_REGION: 20.0}


@dataclass
class EstimateParams:
    """直线折算参数。"""
    detour_factor: float = 1.4      # 直线 → 实际路程
    speed_kmh: float = 22.0
    overhead_minutes: float = 15.0  # 停车、找教室等固定开销


@dataclass
class TravelTable:
    """中心之间跑一趟要多久、多远。"""
    centers: dict[str, Center] = field(default_factory=dict)
    measured: dict[tuple[str, str], tuple[float, float]] = field(default_factory=dict)
    params: EstimateParams = field(default_factory=EstimateParams)

    @classmethod
    def load(cls, centers, csv_path=None, params=None) -> "TravelTable":
        measured: dict[tuple[str, str], tuple[float, float]] = {}
        if csv_path and Path(csv_path).exists():
            with open(csv_path, encoding="utf-8-sig", newline="") as f:
                for row in csv.DictReader(f):
                    a = (row.get("from") or "").strip()
                    b = (row.get("to") or "").strip()
                    if not a or not b:
                        continue
                    try:
                        minutes = float(row["minutes"])
                        km = float(row.get("km") or 0)
                    except (KeyError, TypeError, ValueError):
                        continue
                    measured[(a, b)] = (minutes, km)
                    measured.setdefault((b, a), (minutes, km))
        return cls(centers=dict(centers), measured=measured,
                   params=params or EstimateParams())

    @property
    def campus_of(self) -> dict[str, str]:
        return {n: c.campus for n, c in self.centers.items()}

    @property
    def region_of(self) -> dict[str, str]:
        return {n: c.region for n, c in self.centers.items() if c.region}

    def between(self, a: str, b: str) -> TravelEstimate:
        tier = proximity_tier(a, b, self.campus_of, self.region_of)
        if a == b:
            return TravelEstimate(0.0, 0.0, TravelSource.MAP, tier)

        hit = self.measured.get((a, b))
        if hit:
            return TravelEstimate(hit[0], hit[1], TravelSource.MAP, tier)

        ca = self.centers.get(a)
        cb = self.centers.get(b)
        if ca and cb and ca.has_coordinate and cb.has_coordinate:
            straight = haversine_km(ca.coordinate, cb.coordinate)
            km = straight * self.params.detour_factor
            minutes = km / self.params.speed_kmh * 60 + self.params.overhead_minutes
            return TravelEstimate(minutes, km, TravelSource.ESTIMATE, tier)

        return TravelEstimate(FALLBACK_MINUTES[tier], FALLBACK_KM[tier],
                              TravelSource.TIER, tier)

    def is_feasible(self, a: str, b: str, available_minutes: float, *,
                    safety_margin: float = 10.0) -> bool:
        """这段间隔够不够从 a 赶到 b。"""
        if a == b:
            return True
        return available_minutes >= self.between(a, b).minutes + safety_margin

    def within_distance(self, a: str, b: str, limit_km: float) -> bool:
        return a == b or self.between(a, b).kilometers <= limit_km
