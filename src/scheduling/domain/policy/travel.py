"""转场策略 —— 指导员视角：别到处跑。

反面教材（用户原话）：「8 点在宝安带，10 点又到南山去，下午两点又跑到
宝安，4 点又跑到南山，太折腾。」

两条口径必须一致，否则同一份排班会报出两个数：
  **转场次数按相邻课之间实际发生的中心变更计。A→B→A 记 2 次，不是 1 次。**
历史上求解算 distinct−1、体检算实际事件，同一份排班一个报 19 一个报 25。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TravelSource(Enum):
    """数据来源。报告里必须如实标注，免得把估算当实测看。"""
    MAP = "地图"        # 实测驾车时间/里程
    ESTIMATE = "估算"   # 经纬度直线折算
    TIER = "档位"       # 连坐标都没有时的兜底

    @property
    def is_reliable(self) -> bool:
        return self is TravelSource.MAP


class ProximityTier(Enum):
    """远近四档。

    用户原话：「一般就是一个区内的跨就好一点。宝安区内的就跨宝安区内的，
    宝安就跟南山换嘛，相邻的这样可以换。但尽可能就是同一个区。」

    所以「跨区域」不是一档而是两档 —— 相邻区可以换，不相邻的才是最差。
    哪些区相邻由配置给，不写死：各家对「区域」的划分口径不一样
    （原表用的是「宝安南山区」「罗湖龙岗区」这种合并区）。
    """
    SAME_CAMPUS = "同校区"
    SAME_REGION = "同区域"
    ADJACENT_REGION = "相邻区域"
    CROSS_REGION = "跨区域"

    @property
    def rank(self) -> int:
        """越小越好，可直接用于排序和罚分档位。"""
        return {"同校区": 0, "同区域": 1, "相邻区域": 2, "跨区域": 3}[self.value]


@dataclass(frozen=True)
class TravelEstimate:
    minutes: float
    kilometers: float
    source: TravelSource
    tier: ProximityTier


def count_transfers(centers) -> int:
    """按时间顺序排列的中心序列里，实际发生了几次中心变更。

    A→A→B→A 记 2 次。这是**唯一**的转场口径，求解与体检共用。
    """
    seq = [c for c in centers if c]
    return sum(1 for a, b in zip(seq, seq[1:]) if a != b)


def normalize_adjacency(raw) -> dict[str, frozenset[str]]:
    """把配置里的相邻表补成对称的。

    配置里写「宝安南山区: [福田区]」就够了，不必再写一遍反向 ——
    只写一边而系统只认一边，是这类配置最常见的错。
    """
    out: dict[str, set[str]] = {}
    for a, neighbours in (raw or {}).items():
        for b in neighbours or ():
            out.setdefault(a, set()).add(b)
            out.setdefault(b, set()).add(a)
    return {k: frozenset(v) for k, v in out.items()}


def proximity_tier(center_a: str, center_b: str, campus_of: dict,
                   region_of: dict, adjacency: dict | None = None) -> ProximityTier:
    """两个中心的远近档位。

    **兜底必须保守**：区域不明的一律按最差档算。让两个 None 相等而判成
    「同区域」，会因为缺数据反而**放宽**约束 —— 这是反的。
    没配相邻表时同理，一律按不相邻处理。
    """
    ca, cb = campus_of.get(center_a), campus_of.get(center_b)
    if ca and ca == cb:
        return ProximityTier.SAME_CAMPUS
    ra, rb = region_of.get(center_a), region_of.get(center_b)
    if not ra or not rb:
        return ProximityTier.CROSS_REGION
    if ra == rb:
        return ProximityTier.SAME_REGION
    if rb in (adjacency or {}).get(ra, ()):
        return ProximityTier.ADJACENT_REGION
    return ProximityTier.CROSS_REGION
