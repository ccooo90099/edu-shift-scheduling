"""坐标系转换 —— 国内地图数据混用时最容易出错的地方。

    WGS-84   GPS / OpenStreetMap / OSRM 用的国际标准
    GCJ-02   国内法规要求的加偏坐标，高德、腾讯、Google中国 都是它

两者在深圳一带差 300–700 米。同一份表里混着两种坐标又不标注，
算出来的距离就会莫名其妙偏掉。所以 centers.csv 带一列「坐标系」，
内部一律折算到 WGS-84 再算。

（注：算"两点之间的距离"时，GCJ 偏移在小范围内近似同向，误差大部分会抵消；
真正会出事的是把一个 GCJ 点和一个 WGS 点直接放在一起算。）
"""
import math

WGS84 = "wgs84"
GCJ02 = "gcj02"

_A = 6378245.0                  # 克拉索夫斯基椭球长半轴
_EE = 0.00669342162296594323    # 偏心率平方


def _out_of_china(lon, lat):
    return not (73.66 < lon < 135.05 and 3.86 < lat < 53.55)


def _transform_lat(x, y):
    ret = (-100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y
           + 0.2 * math.sqrt(abs(x)))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * math.pi) + 320 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lon(x, y):
    ret = (300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y
           + 0.1 * math.sqrt(abs(x)))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
    return ret


def _offset(lon, lat):
    d_lat = _transform_lat(lon - 105.0, lat - 35.0)
    d_lon = _transform_lon(lon - 105.0, lat - 35.0)
    rad = lat / 180.0 * math.pi
    magic = 1 - _EE * math.sin(rad) ** 2
    sqrt_magic = math.sqrt(magic)
    d_lat = (d_lat * 180.0) / ((_A * (1 - _EE)) / (magic * sqrt_magic) * math.pi)
    d_lon = (d_lon * 180.0) / (_A / sqrt_magic * math.cos(rad) * math.pi)
    return d_lon, d_lat


def wgs84_to_gcj02(lon, lat):
    if _out_of_china(lon, lat):
        return lon, lat
    d_lon, d_lat = _offset(lon, lat)
    return lon + d_lon, lat + d_lat


def gcj02_to_wgs84(lon, lat):
    """反解。官方没有逆算法，这里用一次偏移近似，误差在米级，够用。"""
    if _out_of_china(lon, lat):
        return lon, lat
    d_lon, d_lat = _offset(lon, lat)
    return lon - d_lon, lat - d_lat


def to_wgs84(lon, lat, datum):
    """把任意来源的点折算到 WGS-84。未知的坐标系按 WGS-84 处理。"""
    if (datum or "").strip().lower() == GCJ02:
        return gcj02_to_wgs84(lon, lat)
    return lon, lat
