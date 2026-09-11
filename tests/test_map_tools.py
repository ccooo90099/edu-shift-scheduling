"""两个地图工具的端到端：中心表补坐标 → 生成通行时间表 → 排班能读到。

用假 provider，不打真网络。
"""
import csv
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import mapapi   # noqa: E402
from engine.travel import Travel, load_geo   # noqa: E402

POINTS = {"石厦科学": (114.045, 22.530), "百花科学": (114.058, 22.548),
          "翠竹科学": (114.133, 22.560)}


class FakeMap:
    """逐点调用型（模拟高德）。按坐标编个确定的时间/里程，方便断言。"""
    name = "fake"
    datum = "gcj02"
    needs_key = False

    def __init__(self, key=None, city="深圳", **kw):
        self.key = key

    def geocode(self, address):
        for name, point in POINTS.items():
            if name in address:
                return point
        return None

    def driving(self, origins, destination):
        out = []
        for lon, lat in origins:
            km = (abs(lon - destination[0]) + abs(lat - destination[1])) * 100
            out.append((km * 3, km))
        return out


class FakeMatrixMap(FakeMap):
    """一次出整个矩阵型（模拟 OSRM）。"""
    name = "fakematrix"
    datum = "wgs84"

    def matrix(self, points):
        size = len(points)
        minutes = [[None] * size for _ in range(size)]
        km = [[None] * size for _ in range(size)]
        for i, (lon1, lat1) in enumerate(points):
            for j, (lon2, lat2) in enumerate(points):
                d = (abs(lon1 - lon2) + abs(lat1 - lat2)) * 100
                minutes[i][j], km[i][j] = d * 3, d
        return minutes, km


@pytest.fixture
def fake_provider(monkeypatch):
    monkeypatch.setitem(mapapi.PROVIDERS, "fake", FakeMap)
    monkeypatch.setitem(mapapi.PROVIDERS, "fakematrix", FakeMatrixMap)


@pytest.fixture
def centers_csv(tmp_path):
    path = tmp_path / "centers.csv"
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["中心", "校区", "区域", "地址", "经度", "纬度"])
        w.writerow(["石厦科学", "石厦", "福田区", "", "", ""])
        w.writerow(["百花科学", "百花", "福田区", "", "", ""])
        w.writerow(["翠竹科学", "翠竹", "罗湖龙岗区", "", "114.133", "22.560"])
        w.writerow(["查不到的中心", "某", "福田区", "", "", ""])
    return path


def run(module_path, argv, monkeypatch):
    import importlib
    monkeypatch.setattr(sys, "argv", ["tool"] + argv)
    module = importlib.import_module(module_path)
    try:
        module.main()
    except SystemExit as e:
        return e.code or 0
    return 0


def read(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def test_补坐标_只动空的_查不到的报错但不影响其他行(centers_csv, fake_provider, monkeypatch):
    code = run("tools.geocode_centers",
               ["--key", "k", "--provider", "fake", "--centers", str(centers_csv)],
               monkeypatch)
    assert code == 1                       # 有一个查不到，整体返回非零

    rows = {r["中心"]: r for r in read(centers_csv)}
    assert float(rows["石厦科学"]["经度"]) == 114.045
    assert float(rows["百花科学"]["纬度"]) == 22.548
    assert rows["翠竹科学"]["经度"] == "114.133"        # 原来就有的没被改写
    assert rows["查不到的中心"]["经度"] == ""            # 查不到的留空，不写垃圾
    assert "深圳石厦科学" in rows["石厦科学"]["地址"]     # 用过的地址写回来方便核对
    assert rows["石厦科学"]["坐标系"] == "gcj02"          # 记下来源，排班时才知道要不要折算


def test_生成通行时间表_并且排班读得到(centers_csv, fake_provider, monkeypatch, tmp_path):
    run("tools.geocode_centers",
        ["--key", "k", "--provider", "fake", "--centers", str(centers_csv)], monkeypatch)

    out = tmp_path / "travel.csv"
    code = run("tools.travel_matrix",
               ["--key", "k", "--provider", "fake", "--centers", str(centers_csv),
                "--out", str(out)], monkeypatch)
    assert code == 0

    rows = read(out)
    assert {r["from"] for r in rows} == set(POINTS)      # 没坐标的中心不参与
    assert len(rows) == len(POINTS) * (len(POINTS) - 1)
    assert all(r["source"] == "fake" for r in rows)
    assert all(float(r["minutes"]) > 0 and float(r["km"]) > 0 for r in rows)

    # 排班侧读得到，且来源标成「地图」
    cfg = {"地理": {"中心坐标表": str(centers_csv), "通行时间表": str(out),
                    "判定方式": "时间", "时间": {"安全余量_分钟": 0}}}
    coords, table = load_geo(cfg)
    campus = {n: n for n in POINTS}
    travel = Travel(cfg, coords, table, campus, dict.fromkeys(POINTS, "福田区"))
    assert travel.source("石厦科学", "百花科学") == "地图"
    assert not travel.used_fallback


def test_没有坐标就拒绝生成矩阵(tmp_path, fake_provider, monkeypatch):
    empty = tmp_path / "centers.csv"
    empty.write_text("中心,经度,纬度\n甲,,\n乙,,\n", encoding="utf-8-sig")
    code = run("tools.travel_matrix",
               ["--key", "k", "--provider", "fake", "--centers", str(empty),
                "--out", str(tmp_path / "t.csv")], monkeypatch)
    assert code and "geocode" in str(code)      # 提示先去补坐标


def test_dry_run不写文件(centers_csv, fake_provider, monkeypatch, tmp_path):
    out = tmp_path / "travel.csv"
    run("tools.travel_matrix",
        ["--key", "k", "--provider", "fake", "--centers", str(centers_csv),
         "--out", str(out), "--dry-run"], monkeypatch)
    assert not out.exists()


def test_一次性矩阵路径_只调一次就出全部(centers_csv, fake_provider, monkeypatch, tmp_path):
    """OSRM 那条路：providers 有 matrix() 时走一次调用，结果要和逐点调用一致。"""
    run("tools.geocode_centers",
        ["--provider", "fake", "--centers", str(centers_csv)], monkeypatch)

    out = tmp_path / "travel.csv"
    code = run("tools.travel_matrix",
               ["--provider", "fakematrix", "--centers", str(centers_csv),
                "--out", str(out)], monkeypatch)
    assert code == 0

    rows = read(out)
    assert len(rows) == len(POINTS) * (len(POINTS) - 1)
    assert all(r["source"] == "fakematrix" for r in rows)
    # 对角线（自己到自己）不该出现在表里
    assert all(r["from"] != r["to"] for r in rows)


def test_amap缺key直接报错不往下跑(centers_csv, monkeypatch, tmp_path):
    code = run("tools.travel_matrix",
               ["--provider", "amap", "--centers", str(centers_csv),
                "--out", str(tmp_path / "t.csv")], monkeypatch)
    assert "key" in str(code)
    assert not (tmp_path / "t.csv").exists()


def test_连堂规则填自动时用推算值(tmp_path):
    """配置写「自动」，引擎要真的去推，而不是当成 None 放行一切。"""
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from engine.health import _check_adjacency, Report

    import pandas as pd
    from engine.slots import parse_slot

    def row(校区, 产品, 时段, 团队ID):
        start, end = parse_slot(时段)
        return {"段次": "段次1", "周": "星期六", "校区": 校区, "程度": "S7",
                "团队类型": "LI", "产品": 产品, "首次服务时间": 时段,
                "_start": start, "_end": end, "团队ID": 团队ID, "主指导员": "某"}

    # 甲校区：课间 20 分钟相接；乙校区：跨午休 90 分钟
    df = pd.DataFrame([
        row("甲", "编程理论", "08:10-10:10", 1),
        row("甲", "双语文化", "10:30-12:30", 2),
        row("乙", "编程理论", "10:30-12:30", 3),
        row("乙", "双语文化", "14:00-16:00", 4),
    ])
    cfg = {"时段": ["08:10-10:10", "10:30-12:30", "13:30-15:30",
                    "14:00-16:00", "16:20-18:20", "18:30-20:30"],
           "连堂": {"分组范围": ["校区", "程度", "团队类型"],
                    "规则": [{"名称": "编程双语连堂", "产品": ["编程理论", "双语文化"],
                              "强度": "硬", "允许中间隔": 0, "最大间隙_分钟": "自动"}]}}

    rep = Report()
    _check_adjacency(df, cfg, rep)
    名称, 强度, 总数, 不夹课, 真挨着, 阈值 = rep.连堂[0]
    assert 阈值 == 20                      # 「自动」被解析成了 20，不是 None
    assert 总数 == 2 and 不夹课 == 2       # 两对中间都没夹课
    assert 真挨着 == 1                     # 但只有甲校区那对在 20 分钟内
    assert any("90 分钟" in f.问题 for f in rep.findings)   # 乙校区被点名
