"""通行时间/距离：来源优先级、两种判定口径、以及地图 API 的解析。"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.mapapi import AMap, MapError   # noqa: E402
from engine.travel import Travel, load_geo   # noqa: E402

COORDS = {"石厦科学": (114.045, 22.530), "百花科学": (114.058, 22.548),
          "翠竹科学": (114.133, 22.560)}
CAMPUS = {"石厦科学": "石厦", "百花科学": "百花", "翠竹科学": "翠竹"}
REGION = {"石厦科学": "福田区", "百花科学": "福田区", "翠竹科学": "罗湖龙岗区"}


def build(mode="时间", table=None, coords=COORDS, **geo):
    cfg = {"地理": dict({"判定方式": mode, "时间": {"安全余量_分钟": 10},
                         "距离": {"上限_km": 8}}, **geo)}
    return Travel(cfg, coords, table or {}, CAMPUS, REGION)


# ── 来源优先级 ────────────────────────────────────────────────────

def test_有地图数据就用地图数据():
    t = build(table={("石厦科学", "百花科学"): (18.0, 6.4)})
    assert t.source("石厦科学", "百花科学") == "地图"
    assert t.minutes("石厦科学", "百花科学") == 18.0
    assert t.km("石厦科学", "百花科学") == 6.4


def test_没有地图数据就用坐标估算():
    t = build()
    assert t.source("石厦科学", "百花科学") == "直线估算"
    # 直线 ~2.3km × 1.4 折算，加 15 分钟固定开销
    assert 15 < t.minutes("石厦科学", "百花科学") < 30


def test_连坐标都没有才退回粗判():
    t = build(coords={})
    assert t.source("石厦科学", "翠竹科学") == "粗判"
    assert t.minutes("石厦科学", "翠竹科学") == 70      # 跨区域
    assert t.minutes("石厦科学", "百花科学") == 40      # 同区域
    assert t.used_fallback


def test_单向的地图数据两个方向都能用():
    cfg = {"地理": {"通行时间表": None}}
    t = Travel(cfg, COORDS, {("A", "B"): (12.0, 3.0), ("B", "A"): (12.0, 3.0)},
               CAMPUS, REGION)
    assert t.minutes("B", "A") == 12.0


# ── 两种判定口径 ──────────────────────────────────────────────────

def test_按时间判定_要算上安全余量():
    t = build(mode="时间", table={("石厦科学", "百花科学"): (18.0, 6.4)})
    ok, why = t.acceptable("石厦科学", "百花科学", 20)     # 18+10=28 > 20
    assert not ok and "赶路只有 20 分钟" in why and "余量" in why
    assert t.acceptable("石厦科学", "百花科学", 30)[0]     # 30 >= 28


def test_按距离判定_只看公里数不看给了多少时间():
    t = build(mode="距离", table={("石厦科学", "翠竹科学"): (25.0, 9.5)})
    ok, why = t.acceptable("石厦科学", "翠竹科学", 999)
    assert not ok and "9.5 km" in why and "8.0 km" in why


def test_按距离判定_没超上限就放行():
    t = build(mode="距离", table={("石厦科学", "百花科学"): (18.0, 6.4)})
    assert t.acceptable("石厦科学", "百花科学", 1)[0]


def test_同一个中心永远可接受():
    t = build()
    assert t.acceptable("石厦科学", "石厦科学", 0) == (True, "")


def test_两种口径对同一对中心可以给出不同结论():
    table = {("石厦科学", "翠竹科学"): (25.0, 9.5)}
    有时间 = 40      # 时间够，但距离超上限
    assert build(mode="时间", table=table).acceptable("石厦科学", "翠竹科学", 有时间)[0]
    assert not build(mode="距离", table=table).acceptable("石厦科学", "翠竹科学", 有时间)[0]


# ── 读表 ──────────────────────────────────────────────────────────

def test_读通行时间表_没有km列也能用(tmp_path):
    path = tmp_path / "travel.csv"
    path.write_text("from,to,minutes\n甲,乙,20\n", encoding="utf-8-sig")
    _, table = load_geo({"地理": {"通行时间表": str(path)}})
    assert table[("甲", "乙")] == (20.0, None)
    assert table[("乙", "甲")] == (20.0, None)


def test_读坐标表_跳过没填经纬度的行(tmp_path):
    path = tmp_path / "centers.csv"
    path.write_text("中心,经度,纬度\n甲,114.0,22.5\n乙,,\n", encoding="utf-8-sig")
    coords, _ = load_geo({"地理": {"中心坐标表": str(path)}})
    assert list(coords) == ["甲"]


def test_文件不存在时安静退回(tmp_path):
    coords, table = load_geo({"地理": {"中心坐标表": str(tmp_path / "no.csv"),
                                      "通行时间表": str(tmp_path / "no2.csv")}})
    assert coords == {} and table == {}


# ── 地图 API ──────────────────────────────────────────────────────

def fake_amap(payload):
    return lambda url, params, timeout=20: payload


def test_高德地理编码():
    client = AMap("k", pause=0, fetch=fake_amap(
        {"status": "1", "geocodes": [{"location": "114.057868,22.543099"}]}))
    assert client.geocode("深圳市福田区百花二路") == (114.057868, 22.543099)


def test_高德查不到地址返回None():
    client = AMap("k", pause=0, fetch=fake_amap({"status": "1", "geocodes": []}))
    assert client.geocode("火星一号") is None


def test_高德报错要带上原因():
    client = AMap("k", pause=0, fetch=fake_amap(
        {"status": "0", "info": "INVALID_USER_KEY", "infocode": "10001"}))
    with pytest.raises(MapError, match="INVALID_USER_KEY"):
        client.geocode("深圳")


def test_驾车结果按origin_id回填而不是按顺序():
    client = AMap("k", pause=0, fetch=fake_amap({"status": "1", "results": [
        {"origin_id": "2", "distance": "8200", "duration": "1500"},
        {"origin_id": "1", "distance": "3100", "duration": "600"}]}))
    out = client.driving([(114.0, 22.5), (114.1, 22.6)], (114.05, 22.54))
    assert out[0] == (10.0, 3.1)
    assert out[1] == (25.0, 8.2)


def test_算不出来的点是None不是塌陷():
    client = AMap("k", pause=0, fetch=fake_amap({"status": "1", "results": [
        {"origin_id": "1", "distance": "3100", "duration": "600"}]}))
    out = client.driving([(114.0, 22.5), (114.1, 22.6)], (114.05, 22.54))
    assert out[1] is None


def test_起点超过100个要报错():
    client = AMap("k", pause=0, fetch=fake_amap({"status": "1", "results": []}))
    with pytest.raises(MapError, match="100"):
        client.driving([(114.0, 22.5)] * 101, (114.0, 22.5))
