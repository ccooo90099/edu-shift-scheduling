"""从排班明细 xlsx 派生领域对象。

⚠️ 这里集中了两类容易静默出错的地方，都有过实际故障：

1. **pandas 的默认值会悄悄丢数据。** `groupby` 默认 `dropna=True`，
   分组键里有空值的行会被整批丢弃；缺了这些行，某个中心可能一条容量
   约束都没有 —— 不报错，只是约束消失。
2. **同一列的两种视图会分叉。** 曾经用 `astype(str)` 过滤（`None` 变成
   非空字符串，通过）却用原列 `.nunique()` 计数（`None` 被 dropna，得 0），
   于是「有标签」的中心派生出 0 间教室。

规则：**过滤和计数必须落在同一个归一化视图上；一切 groupby 显式
`dropna=False`。**
"""
from __future__ import annotations

import pandas as pd

from ...domain.model.curriculum import Grade, Tier, product_of
from ...domain.model.team import Team
from ...domain.model.timeslot import TimeSlot
from ...domain.model.venue import Center, Room

TIME_COL = "首次服务时间"
MISSING = "（未填）"


def normalize_labels(series: pd.Series) -> pd.Series:
    """把一列标签归一成 StringDtype 并去空白。

    `astype("string")` 让 None / NaN / pd.NA 统一成 pd.NA，
    过滤与计数从此看到的是同一个东西。
    """
    return series.astype("string").str.strip()


def valid_mask(series: pd.Series) -> pd.Series:
    labels = normalize_labels(series)
    return labels.notna() & labels.ne("")


def derive_rooms(df: pd.DataFrame) -> dict[str, tuple[list[Room], bool]]:
    """每个中心的教室清单，以及它是不是估计值。

    标签完整 → 按实际教室号建实体。
    标签有缺 → 取「已见教室数」与「各教学日真实时间最大并发」的较大值，
              建占位教室并标记为估计。**部分缺失时已见数不代表完整容量。**
    """
    out: dict[str, tuple[list[Room], bool]] = {}
    if "中心" not in df:
        return out

    has_label = "指导室" in df
    labels = normalize_labels(df["指导室"]) if has_label else None
    valid = valid_mask(df["指导室"]) if has_label else pd.Series(False, index=df.index)

    seen: dict[str, set[str]] = {}
    if has_label:
        named = df[valid].copy()
        named["指导室"] = labels[valid]
        for center, sub in named.groupby("中心", dropna=False):
            seen[str(center)] = set(sub["指导室"].dropna())

    incomplete = set(df.loc[~valid, "中心"].astype(str))

    # 各教学日的真实时间最大并发。dropna=False 是关键：
    # 段次或周为空的行不能被丢掉，否则那个中心可能完全没有容量约束。
    peaks: dict[str, int] = {}
    group_keys = [k for k in ("中心", "段次", "周") if k in df]
    for key, sub in df.groupby(group_keys, dropna=False):
        center = str(key[0] if isinstance(key, tuple) else key)
        if center not in incomplete:
            continue
        slots = []
        for text, n in sub[TIME_COL].value_counts().items():
            try:
                slots.append((TimeSlot.parse(str(text)), int(n)))
            except (ValueError, AttributeError):
                continue
        peak = 0
        for instant in sorted({s.start for s, _ in slots}):
            peak = max(peak, sum(n for s, n in slots if s.start <= instant < s.end))
        peaks[center] = max(peaks.get(center, 0), peak)

    for center in sorted(set(df["中心"].astype(str))):
        observed = seen.get(center, set())
        estimated = peaks.get(center, 0)
        if center in incomplete:
            count = max(len(observed), estimated)
            ids = sorted(observed) + ["估%d" % i for i in
                                      range(1, count - len(observed) + 1)]
            out[center] = ([Room(center, r) for r in ids], True)
        else:
            out[center] = ([Room(center, r) for r in sorted(observed)], False)
    return out


def derive_centers(df: pd.DataFrame) -> dict[str, Center]:
    rooms = derive_rooms(df)
    centers: dict[str, Center] = {}
    for name, sub in df.groupby("中心", dropna=False):
        name = str(name)
        room_list, estimated = rooms.get(name, ([], True))
        region = ""
        if "区域" in sub:
            vals = normalize_labels(sub["区域"]).dropna()
            region = str(vals.iloc[0]) if len(vals) else ""
        centers[name] = Center(
            name=name, campus=Center.campus_of(name), region=region,
            rooms=room_list, rooms_are_estimated=estimated)
    return centers


def derive_teams(df: pd.DataFrame) -> list[Team]:
    """把一份排班明细当成待排清单。时段与指导员作废，留作对照。"""
    teams: list[Team] = []
    for i, row in df.iterrows():
        try:
            grade = Grade(str(row["程度"]).strip())
            tier = Tier(str(row["团队类型"]).strip())
            product = product_of(str(row["产品"]).strip())
        except (ValueError, KeyError):
            continue        # 认不出来的行跳过，但不静默 —— 调用方对比行数
        center = str(row["中心"])
        original = None
        text = str(row.get(TIME_COL, "") or "").strip()
        if text:
            try:
                original = TimeSlot.parse(text)
            except ValueError:
                original = None
        teams.append(Team(
            id=str(row.get("团队ID", i)), center=center,
            campus=Center.campus_of(center),
            region=str(row.get("区域", "") or ""),
            grade=grade, product=product, tier=tier,
            name=str(row.get("团队名称", "") or ""),
            is_promotional=str(row.get("是否促销", "")).strip() in ("是", "Y", "1"),
            original_slot=original,
            original_instructor=str(row.get("主指导员", "") or "") or None))
    return teams
