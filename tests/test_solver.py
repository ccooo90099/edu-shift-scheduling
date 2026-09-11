"""求解器：硬约束必须真的硬，软约束方向要对。

用小规模合成问题，每条只盯一件事 —— 真实数据上出了问题很难定位到具体哪条约束。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.inputs import Instructor, Team   # noqa: E402
from engine.solver import solve   # noqa: E402

SLOTS = ["08:10-10:10", "10:30-12:30", "13:30-15:30",
         "14:00-16:00", "16:20-18:20", "18:30-20:30"]


def base_cfg(**over):
    cfg = {
        "时段": SLOTS,
        "冲突口径": {"分组字段": ["校区", "程度"]},
        "连堂": {"分组范围": ["校区", "程度", "团队类型"], "规则": []},
        "地理": {"判定方式": "时间", "时间": {"安全余量_分钟": 0}},
        "权重": {},
    }
    cfg.update(over)
    return cfg


def team(tid, 产品, 中心="甲中心", 校区="甲", 程度="S7", 团队类型="LI", 区域="A区"):
    return Team(团队ID=tid, 段次="段次1", 周="星期六", 区域=区域, 中心=中心,
                校区=校区, 程度=程度, 产品=产品, 团队类型=团队类型)


def teacher(name, 产品, **kw):
    return Instructor(姓名=name, 可教产品=set(产品), **kw)


def run(teams, instructors, rooms=None, cfg=None, **kw):
    rooms = rooms or {t.中心: 10 for t in teams}
    return solve(teams, {i.姓名: i for i in instructors}, rooms,
                 cfg or base_cfg(), time_limit=20, workers=2, **kw)


# ── H2：同校区同程度，一个时段只能一个产品 ──────────────────────

def test_同校区同程度不同产品必须错开():
    teams = [team("a", "编程理论"), team("b", "双语文化")]
    res = run(teams, [teacher("甲", ["编程理论", "双语文化"]),
                      teacher("乙", ["编程理论", "双语文化"])])
    assert not res.未排上
    slots = {res.assignments[t.团队ID][0] for t in teams}
    assert len(slots) == 2, "两个产品被排到了同一个时段"


def test_重叠时段也不能放两个产品_两个方向都要管():
    """13:30-15:30 和 14:00-16:00 在时间上重叠。

    这条是真出过的 bug：重叠约束只写了 p1 < p2 一个方向，
    反方向（编程在前、双语在后）漏掉了，重叠时段就会同时出现两个产品。
    只开这两个时段，逼求解器必须面对这个重叠。
    """
    cfg = base_cfg(时段=["13:30-15:30", "14:00-16:00"])
    teams = [team("a", "编程理论"), team("b", "双语文化")]
    res = run(teams, [teacher("甲", ["编程理论"]), teacher("乙", ["双语文化"])], cfg=cfg)
    # 两个产品塞不进两个重叠的时段，只能有一个排上
    assert len(res.未排上) == 1


def test_同产品可以并排在一个时段():
    """H2 管的是"不同产品"，同一个产品的平行班挤一个时段是允许的。"""
    cfg = base_cfg(时段=["08:10-10:10"])
    teams = [team("a", "编程理论"), team("b", "编程理论")]
    res = run(teams, [teacher("甲", ["编程理论"]), teacher("乙", ["编程理论"])], cfg=cfg)
    assert not res.未排上
    assert {res.assignments[t.团队ID][0] for t in teams} == {"08:10-10:10"}


def test_不同程度可以同时段排不同产品():
    """H2 是按年级分的 —— S7 和 S8 互不影响。"""
    cfg = base_cfg(时段=["08:10-10:10"])
    teams = [team("a", "编程理论", 程度="S7"), team("b", "双语文化", 程度="S8")]
    res = run(teams, [teacher("甲", ["编程理论"]), teacher("乙", ["双语文化"])], cfg=cfg)
    assert not res.未排上


# ── H1 / H3 / H4 ────────────────────────────────────────────────

def test_一个老师同一时段不能带两个团队():
    cfg = base_cfg(时段=["08:10-10:10", "10:30-12:30"])
    teams = [team("a", "编程理论"), team("b", "编程理论")]
    res = run(teams, [teacher("独苗", ["编程理论"])], cfg=cfg)
    assert not res.未排上
    assert res.assignments["a"][0] != res.assignments["b"][0]


def test_教室不够就排不下():
    cfg = base_cfg(时段=["08:10-10:10"])
    teams = [team("a", "编程理论"), team("b", "编程理论")]
    res = run(teams, [teacher("甲", ["编程理论"]), teacher("乙", ["编程理论"])],
              rooms={"甲中心": 1}, cfg=cfg)
    assert len(res.未排上) == 1


def test_没有合格老师的团队排不上():
    res = run([team("a", "溯源")], [teacher("甲", ["编程理论"])])
    assert res.未排上 == ["a"]
    assert not res.可行


def test_老师的不可用时段会被绕开():
    cfg = base_cfg(时段=["08:10-10:10", "10:30-12:30"])
    res = run([team("a", "编程理论")],
              [teacher("甲", ["编程理论"], 不可用时段={"08:10-10:10"})], cfg=cfg)
    assert res.assignments["a"][0] == "10:30-12:30"


def test_单日节数上限生效():
    cfg = base_cfg(时段=["08:10-10:10", "10:30-12:30", "14:00-16:00"])
    teams = [team(str(i), "编程理论") for i in range(3)]
    res = run(teams, [teacher("甲", ["编程理论"], 单日最多节数=2)], cfg=cfg)
    assert len(res.未排上) == 1


# ── S1 连堂 ─────────────────────────────────────────────────────

def test_连堂规则会把两个产品排到相接时段():
    cfg = base_cfg()
    cfg["连堂"]["规则"] = [{"名称": "编程双语连堂", "产品": ["编程理论", "双语文化"],
                            "强度": "硬", "允许中间隔": 0, "最大间隙_分钟": "自动"}]
    teams = [team("a", "编程理论"), team("b", "双语文化")]
    res = run(teams, [teacher("甲", ["编程理论"]), teacher("乙", ["双语文化"])], cfg=cfg)
    assert not res.连堂未满足
    from engine.slots import parse_slot
    s1, s2 = (parse_slot(res.assignments["a"][0]), parse_slot(res.assignments["b"][0]))
    早, 晚 = sorted([s1, s2])
    assert 晚[0] - 早[1] <= 20, "两节课之间等太久了"


def test_连堂排不下时会被报出来而不是直接无解():
    """只给一个时段，连堂不可能满足 —— 要出解并点名，不能只回一句 INFEASIBLE。"""
    cfg = base_cfg(时段=["08:10-10:10"])
    cfg["连堂"]["规则"] = [{"名称": "编程双语连堂", "产品": ["编程理论", "双语文化"],
                            "强度": "硬", "允许中间隔": 0, "最大间隙_分钟": "自动"}]
    teams = [team("a", "编程理论"), team("b", "双语文化")]
    res = run(teams, [teacher("甲", ["编程理论"]), teacher("乙", ["双语文化"])], cfg=cfg)
    assert res.连堂未满足, "应该点名说哪个学生群没满足"
    assert res.连堂未满足[0][2] == "硬"
    assert not res.可行


# ── S3 跑场 ─────────────────────────────────────────────────────

def test_赶不及的跨中心组合会被禁掉():
    """08:10 到 10:30 只有 20 分钟，跨区域来不及。"""
    cfg = base_cfg(时段=["08:10-10:10", "10:30-12:30"])
    teams = [team("a", "编程理论", 中心="甲中心", 校区="甲", 区域="A区"),
             team("b", "编程理论", 中心="乙中心", 校区="乙", 区域="B区")]
    res = run(teams, [teacher("独苗", ["编程理论"])], cfg=cfg)
    assert len(res.未排上) == 1, "一个老师不可能 20 分钟跨区赶场"


def test_午休那档足够跨区赶场():
    cfg = base_cfg(时段=["10:30-12:30", "14:00-16:00"])
    teams = [team("a", "编程理论", 中心="甲中心", 校区="甲", 区域="A区"),
             team("b", "编程理论", 中心="乙中心", 校区="乙", 区域="B区")]
    res = run(teams, [teacher("独苗", ["编程理论"])], cfg=cfg)
    assert not res.未排上, "90 分钟午休足够跨区"


# ── 修复模式 ────────────────────────────────────────────────────

def test_修复模式会尽量保持原样():
    cfg = base_cfg(时段=["08:10-10:10", "10:30-12:30"])
    teams = [team("a", "编程理论")]
    teams[0].原时段, teams[0].原主指导员 = "10:30-12:30", "乙"
    seed = {"a": ("10:30-12:30", "乙")}
    res = run(teams, [teacher("甲", ["编程理论"]), teacher("乙", ["编程理论"])],
              cfg=cfg, seed=seed, weights={"与原排班不同": 500})
    assert res.assignments["a"] == ("10:30-12:30", "乙")
