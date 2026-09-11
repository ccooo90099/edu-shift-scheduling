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
    """按坐标编个确定的时间/里程，方便断言。"""
    name = "fake"

    def __init__(self, key, city="深圳", **kw):
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


@pytest.fixture
def fake_provider(monkeypatch):
    monkeypatch.setitem(mapapi.PROVIDERS, "fake", FakeMap)


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
