"""坐标系转换 —— 混用 OSM(WGS-84) 和高德(GCJ-02) 时不出错的前提。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.coords import gcj02_to_wgs84, to_wgs84, wgs84_to_gcj02   # noqa: E402
from engine.travel import haversine_km   # noqa: E402

SHENZHEN = (114.057868, 22.543099)


def meters(a, b):
    return haversine_km(a[0], a[1], b[0], b[1]) * 1000


def test_深圳一带两个坐标系差几百米():
    offset = meters(SHENZHEN, wgs84_to_gcj02(*SHENZHEN))
    assert 300 < offset < 900, "偏移 %.0f 米，超出预期范围" % offset


def test_来回转换能还原到米级():
    assert meters(SHENZHEN, gcj02_to_wgs84(*wgs84_to_gcj02(*SHENZHEN))) < 5


def test_国外坐标原样不动():
    berlin = (13.38, 52.51)
    assert wgs84_to_gcj02(*berlin) == berlin
    assert gcj02_to_wgs84(*berlin) == berlin


def test_按坐标系折算():
    gcj = wgs84_to_gcj02(*SHENZHEN)
    assert meters(to_wgs84(*gcj, "gcj02"), SHENZHEN) < 5
    assert to_wgs84(*gcj, "wgs84") == gcj          # 声明是 WGS-84 就不动
    assert to_wgs84(*gcj, None) == gcj             # 没声明按 WGS-84 处理
    assert to_wgs84(*gcj, "GCJ02") != gcj          # 大小写不敏感


def test_混用两种坐标算距离会错几百米():
    """这就是要记录坐标系的原因 —— 一个 GCJ 点配一个 WGS 点，凭空多出几百米。"""
    a_wgs = SHENZHEN
    b_wgs = (114.133, 22.560)
    b_gcj = wgs84_to_gcj02(*b_wgs)

    对的 = haversine_km(*a_wgs, *b_wgs) * 1000
    错的 = haversine_km(*a_wgs, *b_gcj) * 1000
    assert abs(错的 - 对的) > 200

    # 折算之后就对上了
    修好的 = haversine_km(*a_wgs, *to_wgs84(*b_gcj, "gcj02")) * 1000
    assert abs(修好的 - 对的) < 5
