"""坐标系换算 —— 把任意来源的点折算到 WGS-84。

国内三家地图各用各的坐标系，在深圳一带两两相差 **300–700 米**：

    WGS-84   国际标准        天地图、OpenStreetMap
    GCJ-02   火星坐标        高德、腾讯
    BD-09    百度坐标        在 GCJ-02 基础上**再偏一次**

⚠️ 两个曾经踩过的坑：

1. **百度不是 GCJ-02。** 文档里一度写「高德腾讯百度都是火星坐标」，
   把 BD-09 当 GCJ-02 处理会再差几百米。
2. **未知坐标系不能静默当成 WGS-84。** 老实现 `to_wgs84()` 只识别 GCJ-02，
   其余原样返回 —— 一个标着 `bd09` 的点会被当作 WGS-84 使用，
   偏几百米且不报错。这正是最难发现的一类错误。
"""
from __future__ import annotations

import math

from ...domain.model.venue import Coordinate, Datum

_X_PI = math.pi * 3000.0 / 180.0
_A = 6378245.0                  # 克拉索夫斯基椭球长半轴
_EE = 0.00669342162296594323    # 偏心率平方


def _out_of_china(lon: float, lat: float) -> bool:
    """境外不做偏移 —— GCJ-02 只在国境内生效。"""
    return not (73.66 < lon < 135.05 and 3.86 < lat < 53.55)


def _transform_lat(x: float, y: float) -> float:
    ret = (-100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y
           + 0.2 * math.sqrt(abs(x)))
    ret += (20.0 * math.sin(6.0 * x * math.pi)
            + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * math.pi)
            + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * math.pi)
            + 320 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lon(x: float, y: float) -> float:
    ret = (300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y
           + 0.1 * math.sqrt(abs(x)))
    ret += (20.0 * math.sin(6.0 * x * math.pi)
            + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * math.pi)
            + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * math.pi)
            + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
    return ret


def _delta(lon: float, lat: float) -> tuple[float, float]:
    d_lat = _transform_lat(lon - 105.0, lat - 35.0)
    d_lon = _transform_lon(lon - 105.0, lat - 35.0)
    rad = lat / 180.0 * math.pi
    magic = 1 - _EE * math.sin(rad) ** 2
    sqrt_magic = math.sqrt(magic)
    d_lat = (d_lat * 180.0) / ((_A * (1 - _EE)) / (magic * sqrt_magic) * math.pi)
    d_lon = (d_lon * 180.0) / (_A / sqrt_magic * math.cos(rad) * math.pi)
    return d_lon, d_lat


def wgs84_to_gcj02(lon: float, lat: float) -> tuple[float, float]:
    if _out_of_china(lon, lat):
        return lon, lat
    d_lon, d_lat = _delta(lon, lat)
    return lon + d_lon, lat + d_lat


def gcj02_to_wgs84(lon: float, lat: float) -> tuple[float, float]:
    if _out_of_china(lon, lat):
        return lon, lat
    d_lon, d_lat = _delta(lon, lat)
    return lon - d_lon, lat - d_lat


def gcj02_to_bd09(lon: float, lat: float) -> tuple[float, float]:
    z = math.sqrt(lon * lon + lat * lat) + 0.00002 * math.sin(lat * _X_PI)
    theta = math.atan2(lat, lon) + 0.000003 * math.cos(lon * _X_PI)
    return z * math.cos(theta) + 0.0065, z * math.sin(theta) + 0.006


def bd09_to_gcj02(lon: float, lat: float) -> tuple[float, float]:
    x, y = lon - 0.0065, lat - 0.006
    z = math.sqrt(x * x + y * y) - 0.00002 * math.sin(y * _X_PI)
    theta = math.atan2(y, x) - 0.000003 * math.cos(x * _X_PI)
    return z * math.cos(theta), z * math.sin(theta)


def bd09_to_wgs84(lon: float, lat: float) -> tuple[float, float]:
    return gcj02_to_wgs84(*bd09_to_gcj02(lon, lat))


def wgs84_to_bd09(lon: float, lat: float) -> tuple[float, float]:
    return gcj02_to_bd09(*wgs84_to_gcj02(lon, lat))


_TO_WGS84 = {
    Datum.WGS84: lambda lon, lat: (lon, lat),
    Datum.GCJ02: gcj02_to_wgs84,
    Datum.BD09: bd09_to_wgs84,
}


def to_wgs84(coordinate: Coordinate) -> Coordinate:
    """折算到 WGS-84。

    **未知坐标系直接报错，绝不静默通过。** 宁可让这条记录进「待补齐」清单，
    也不能给出一个偏几百米却看起来正常的坐标。
    """
    convert = _TO_WGS84.get(coordinate.datum)
    if convert is None:
        raise ValueError(
            "未知坐标系 %r，拒绝换算。已知：%s。"
            "静默按 WGS-84 处理会让距离偏差几百米且不报错。"
            % (coordinate.datum, "、".join(d.value for d in _TO_WGS84)))
    lon, lat = convert(coordinate.longitude, coordinate.latitude)
    return Coordinate(lon, lat, Datum.WGS84)


def haversine_km(a: Coordinate, b: Coordinate) -> float:
    """两点直线距离（公里）。两端都先折算到 WGS-84，避免混用坐标系。"""
    p, q = to_wgs84(a), to_wgs84(b)
    r = 6371.0088
    φ1, φ2 = math.radians(p.latitude), math.radians(q.latitude)
    dφ = φ2 - φ1
    dλ = math.radians(q.longitude - p.longitude)
    h = math.sin(dφ / 2) ** 2 + math.cos(φ1) * math.cos(φ2) * math.sin(dλ / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))
