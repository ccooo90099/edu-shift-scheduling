"""坐标系换算 —— R9 的回归测试。"""
import math

import pytest

from scheduling.domain.model.venue import Coordinate, Datum
from scheduling.infrastructure.maps.datum import (
    bd09_to_wgs84, gcj02_to_wgs84, haversine_km, to_wgs84,
    wgs84_to_bd09, wgs84_to_gcj02)

深圳 = (114.0579, 22.5431)


def test_三种坐标系来回换算能还原():
    for fwd, back in [(wgs84_to_gcj02, gcj02_to_wgs84),
                      (wgs84_to_bd09, bd09_to_wgs84)]:
        lon, lat = back(*fwd(*深圳))
        assert math.isclose(lon, 深圳[0], abs_tol=1e-5)
        assert math.isclose(lat, 深圳[1], abs_tol=1e-5)


def _as_wgs(lon, lat):
    """把一串经纬度数字硬当成 WGS-84 —— 模拟 datum 标错的情形。"""
    return Coordinate(lon, lat, Datum.WGS84)


def test_同一地点的三种表示_归一后必须重合():
    """haversine_km 会先把两端折算到 WGS-84，所以同一地点无论用哪种
    坐标系表示，算出来的距离都该是 0。这是它存在的理由。"""
    wgs = Coordinate(*深圳, Datum.WGS84)
    gcj = Coordinate(*wgs84_to_gcj02(*深圳), Datum.GCJ02)
    bd = Coordinate(*wgs84_to_bd09(*深圳), Datum.BD09)
    for c in (wgs, gcj, bd):
        assert haversine_km(c, wgs) < 0.002


def test_三种坐标系的原始数字两两相差可观():
    """把数字当成 WGS-84 直接比 —— 这才是「混用坐标系」的实际后果。"""
    wgs = _as_wgs(*深圳)
    gcj = _as_wgs(*wgs84_to_gcj02(*深圳))
    bd = _as_wgs(*wgs84_to_bd09(*深圳))

    assert 0.3 < haversine_km(wgs, gcj) < 0.8, "WGS↔GCJ 在深圳差 300-700 米"
    assert haversine_km(gcj, bd) > 0.05, "BD-09 在 GCJ-02 之上还有偏移"
    assert haversine_km(wgs, bd) > haversine_km(wgs, gcj), "百度偏得更远"


def test_把百度点误当作火星坐标会差出可观距离():
    """这条就是 R9 的危害：datum 标错不会报错，只会让距离悄悄不对。"""
    真 = Coordinate(*wgs84_to_bd09(*深圳), Datum.BD09)
    误标 = Coordinate(真.longitude, 真.latitude, Datum.GCJ02)
    assert haversine_km(to_wgs84(真), to_wgs84(误标)) > 0.05


def test_未知坐标系直接报错而不是静默当WGS84():
    class 假 :
        value = "unknown"
    bad = Coordinate(*深圳, 假())
    with pytest.raises(ValueError, match="未知坐标系"):
        to_wgs84(bad)


def test_地图来源决定坐标系_未知来源拒绝猜():
    assert Coordinate.from_map_source(*深圳, "高德").datum is Datum.GCJ02
    assert Coordinate.from_map_source(*深圳, "百度").datum is Datum.BD09
    assert Coordinate.from_map_source(*深圳, "天地图").datum is Datum.WGS84
    with pytest.raises(ValueError, match="未知地图来源"):
        Coordinate.from_map_source(*深圳, "某某地图")


def test_境外坐标不做偏移():
    伦敦 = (-0.1276, 51.5072)
    assert wgs84_to_gcj02(*伦敦) == 伦敦
