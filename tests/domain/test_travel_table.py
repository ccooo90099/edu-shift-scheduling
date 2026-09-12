"""通行时间 —— 来源优先级与保守兜底。"""
from scheduling.domain.model.venue import Center, Coordinate, Datum
from scheduling.domain.policy.travel import ProximityTier, TravelSource
from scheduling.infrastructure.maps.travel_table import TravelTable

def 中心(name, campus=None, region="", lon=None, lat=None):
    coord = Coordinate(lon, lat, Datum.WGS84) if lon else None
    return Center(name, campus or Center.campus_of(name), region, coordinate=coord)


def test_来源优先级_实测优先于估算优先于档位(tmp_path):
    csv_path = tmp_path / "travel.csv"
    csv_path.write_text("from,to,minutes,km,source\n甲,乙,25,9.0,amap\n",
                        encoding="utf-8")
    centers = {c.name: c for c in [
        中心("甲", region="福田", lon=114.05, lat=22.54),
        中心("乙", region="福田", lon=114.12, lat=22.55),
        中心("丙", region="南山")]}
    t = TravelTable.load(centers, csv_path)

    assert t.between("甲", "乙").source is TravelSource.MAP
    assert t.between("甲", "乙").minutes == 25
    assert t.between("甲", "丙").source is TravelSource.TIER, "丙没坐标，只能档位兜底"


def test_有坐标无实测时走直线估算():
    centers = {c.name: c for c in [
        中心("甲", region="福田", lon=114.05, lat=22.54),
        中心("乙", region="福田", lon=114.12, lat=22.55)]}
    e = TravelTable.load(centers).between("甲", "乙")
    assert e.source is TravelSource.ESTIMATE
    assert 0 < e.kilometers < 20 and e.minutes > 15


def test_同校区两栋楼算同校区():
    centers = {c.name: c for c in [中心("百花科学"), 中心("百花文学")]}
    e = TravelTable.load(centers).between("百花科学", "百花文学")
    assert e.tier is ProximityTier.SAME_CAMPUS


def test_区域缺失时兜底按跨区域而不是同区域():
    """缺数据不该反而放宽约束。"""
    centers = {c.name: c for c in [中心("甲"), 中心("乙")]}
    e = TravelTable.load(centers).between("甲", "乙")
    assert e.tier is ProximityTier.CROSS_REGION
    assert e.minutes == 70, "跨区域兜底是 70 分钟，不是同区域的 40"


def test_赶不赶得及要算上安全余量():
    centers = {c.name: c for c in [中心("甲", region="福田"), 中心("乙", region="南山")]}
    t = TravelTable.load(centers)      # 跨区域兜底 70 分钟
    assert not t.is_feasible("甲", "乙", 20)
    assert not t.is_feasible("甲", "乙", 75), "70 + 10 余量 = 80"
    assert t.is_feasible("甲", "乙", 90)
    assert t.is_feasible("甲", "甲", 0), "同一个中心不用赶路"


def test_实测表双向可查():
    """csv 只写了一个方向，反向也要能查到。"""
    t = TravelTable(measured={}, centers={})
    t.measured[("甲", "乙")] = (25.0, 9.0)
    t.measured.setdefault(("乙", "甲"), (25.0, 9.0))
    assert t.between("乙", "甲").minutes == 25


# ── 相邻区域（用户补充）─────────────────────────────────────

def test_跨区分两档_相邻区好过不相邻():
    """用户原话：「宝安区内的就跨宝安区内的，宝安就跟南山换嘛，
    相邻的这样可以换。但尽可能就是同一个区。」"""
    centers = {c.name: c for c in [
        中心("宝安甲", region="宝安"), 中心("宝安乙", region="宝安"),
        中心("南山甲", region="南山"), 中心("龙岗甲", region="龙岗")]}
    t = TravelTable.load(centers, adjacency={"宝安": ["南山"]})

    assert t.between("宝安甲", "宝安乙").tier is ProximityTier.SAME_REGION
    assert t.between("宝安甲", "南山甲").tier is ProximityTier.ADJACENT_REGION
    assert t.between("宝安甲", "龙岗甲").tier is ProximityTier.CROSS_REGION


def test_四档的好坏顺序与兜底时间一致():
    assert (ProximityTier.SAME_CAMPUS.rank < ProximityTier.SAME_REGION.rank
            < ProximityTier.ADJACENT_REGION.rank < ProximityTier.CROSS_REGION.rank)
    from scheduling.infrastructure.maps.travel_table import FALLBACK_MINUTES
    times = [FALLBACK_MINUTES[t] for t in sorted(ProximityTier, key=lambda x: x.rank)]
    assert times == sorted(times), "档位越差，兜底时间必须越长"


def test_相邻表只写一边也生效():
    """配置里写「宝安: [南山]」就够，不必再写一遍「南山: [宝安]」——
    只写一边而系统只认一边，是这类配置最常见的错。"""
    centers = {c.name: c for c in [中心("宝安甲", region="宝安"),
                                   中心("南山甲", region="南山")]}
    t = TravelTable.load(centers, adjacency={"宝安": ["南山"]})
    assert t.between("南山甲", "宝安甲").tier is ProximityTier.ADJACENT_REGION


def test_没配相邻表时一律按最差档而不是相邻():
    """缺数据不该反而放宽约束。"""
    centers = {c.name: c for c in [中心("甲", region="宝安"),
                                   中心("乙", region="南山")]}
    assert TravelTable.load(centers).between("甲", "乙").tier \
        is ProximityTier.CROSS_REGION
