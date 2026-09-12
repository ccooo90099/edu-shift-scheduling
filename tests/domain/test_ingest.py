"""入库适配 —— R11/R12 的回归测试。"""
import numpy as np
import pandas as pd

from scheduling.infrastructure.spreadsheet.ingest import derive_rooms

def 表(rows):
    return pd.DataFrame(rows)

def 行(center="C", 段次="S", 周="D", 时段="08:10-10:10", 教室=None):
    return {"中心": center, "段次": 段次, "周": 周,
            "首次服务时间": 时段, "指导室": 教室}


def _间数(df):
    (rooms, _), = derive_rooms(df).values()
    return len(rooms)


def _是估计(df):
    (_, est), = derive_rooms(df).values()
    return est


def test_R11_空标签不再派生0间():
    """None/NaN/pd.NA 曾让 derive_rooms 返回 0，H3 对该中心完全失效。"""
    for 空 in (None, np.nan, pd.NA):
        assert _间数(表([行(教室=空), 行(教室=空)])) == 2


def test_R11_空白与空串本来就正确_不要改坏():
    for 空 in ("  ", ""):
        assert _间数(表([行(教室=空), 行(教室=空)])) == 2


def test_R11_混合标签取较大值而不是只数已见的():
    """[None, '02'] 曾返回 1 —— 不触发短路，静默低估容量造成假性不可行。"""
    assert _间数(表([行(教室=None), 行(教室="02")])) == 2


def test_R12_段次或周为空的行不能被groupby静默丢掉():
    """pandas groupby 默认 dropna=True。这些行一丢，该中心可能
    连一条容量约束都没有 —— 不报错，只是约束消失。"""
    assert _间数(表([行(段次=np.nan, 教室=None), 行(段次=np.nan, 教室=None)])) == 2
    assert _间数(表([行(周=np.nan, 教室=None), 行(周=np.nan, 教室=None)])) == 2


def test_跨教学日不虚增():
    assert _间数(表([行(周="周六", 教室=None), 行(周="周日", 教室=None)])) == 1


def test_重叠时段的并发要算进峰值():
    df = 表([行(时段="13:30-15:30", 教室=None), 行(时段="14:00-16:00", 教室=None)])
    assert _间数(df) == 2, "两档时间重叠，峰值是 2"


def test_端点相接不算并发():
    df = 表([行(时段="08:00-10:00", 教室=None), 行(时段="10:00-12:00", 教室=None)])
    assert _间数(df) == 1


def test_完整标签按实际教室数且不标记为估计():
    df = 表([行(教室="01"), 行(教室="02")])
    assert _间数(df) == 2 and not _是估计(df)
    assert _是估计(表([行(教室=None), 行(教室="02")])), "有缺失就必须标为估计"
