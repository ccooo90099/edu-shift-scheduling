"""读配置、读排班明细，并补上派生字段（校区、班序、起止分钟）。"""
import re

import pandas as pd
import yaml

TIME_COL = "首次服务时间"

from .slots import parse_slot   # noqa: E402


def load_config(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def add_campus(df, cfg):
    """中心 → 校区：百花科学 + 百花文学 = 百花（同校区两栋楼）。"""
    campus = cfg.get("校区", {}) or {}
    if not campus.get("由中心推导", True):
        if "校区" not in df.columns:
            df["校区"] = df["中心"]
        return df

    keep = set(campus.get("不合并") or [])
    suffixes = campus.get("合并后缀") or []
    pattern = "(" + "|".join(suffixes) + ")$" if suffixes else None
    df["校区"] = df["中心"].map(
        lambda n: n if (n in keep or not pattern) else re.sub(pattern, "", n))
    return df


def load_schedule(path, cfg, sheet=None):
    df = pd.read_excel(path, sheet_name=sheet if sheet else 0)
    df = df.map(lambda v: v.strip() if isinstance(v, str) else v)
    df = add_campus(df, cfg)
    if "团队名称" in df.columns:
        df["班序"] = df["团队名称"].astype(str).str.extract(r"(\d+)$")
    # 排班结果里"没排上"的团队时段是空的。直接解析会炸，
    # 但这些行本来就没法参与冲突判定 —— 丢掉并说明，不要让整个体检挂掉。
    blank = df[TIME_COL].isna() | (df[TIME_COL].astype(str).str.strip() == "")
    df.attrs["未排上行数"] = int(blank.sum())
    df = df[~blank].copy()
    if df.empty:
        raise ValueError("表里没有一行填了「%s」—— 是不是所有团队都没排上？" % TIME_COL)

    df[["_start", "_end"]] = df[TIME_COL].apply(lambda t: pd.Series(parse_slot(t)))
    return df
