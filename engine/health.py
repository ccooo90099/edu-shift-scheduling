"""排班体检 —— 按配置的口径找出违规，并按同一套权重打分。

体检和排班器共用配置与权重，所以"排得好不好"始终是同一把尺子：
先给手工排班打分，排班器排完再打一次，差多少一目了然。
"""
import statistics
from dataclasses import dataclass, field
from itertools import combinations

from .data import TIME_COL, load_schedule
from .slots import derive_adjacency_limit, make_gap_counter, overlaps
from .travel import Travel, load_geo


@dataclass
class Finding:
    级别: str
    问题: str
    位置: str
    明细: str


@dataclass
class Report:
    团队数: int = 0
    未排上行数: int = 0
    中心数: int = 0
    校区数: int = 0
    指导员数: int = 0
    冲突口径: str = ""
    老师撞车: int = 0
    产品撞车对数: int = 0
    产品撞车团队数: int = 0
    教室撞车: int = 0
    连堂: list = field(default_factory=list)     # (名称, 强度, 总数, 不夹课, 真挨着, 阈值)
    间隔阈值说明: str = ""
    当日人次: int = 0
    单中心人次: int = 0
    转场次数: int = 0
    赶不及次数: int = 0
    转场里程: float = 0.0
    转场按来源: dict = field(default_factory=dict)
    判定方式: str = ""
    空档段数: int = 0
    有空档人次: int = 0
    多节课人次: int = 0
    人均团队: float = 0.0
    最多团队: int = 0
    工作量方差: float = 0.0
    罚分: float = 0.0
    用了粗判: bool = False
    findings: list = field(default_factory=list)

    @property
    def 硬约束违规(self):
        return self.老师撞车 + self.产品撞车对数 + self.教室撞车

    @property
    def 可行(self):
        return self.硬约束违规 == 0


def _check_teacher_clash(df, rep):
    for key, sub in df.groupby(["段次", "周", "主指导员"]):
        for x, y in combinations(sub.to_dict("records"), 2):
            if overlaps((x["_start"], x["_end"]), (y["_start"], y["_end"])):
                rep.老师撞车 += 1
                rep.findings.append(Finding(
                    "H1", "老师同时段撞车", "%s %s %s" % key,
                    "%s @%s 与 %s @%s" % (x["中心"], x[TIME_COL], y["中心"], y[TIME_COL])))


def _check_product_clash(df, cfg, rep):
    keys = cfg["冲突口径"]["分组字段"]
    missing = [k for k in keys if k not in df.columns]
    if missing:
        raise ValueError("配置里的分组字段在表中不存在：%s" % "、".join(missing))

    dirty = set()
    for key, sub in df.groupby(["段次", "周"] + keys):
        for x, y in combinations(sub.to_dict("records"), 2):
            if x["产品"] != y["产品"] and overlaps((x["_start"], x["_end"]),
                                                  (y["_start"], y["_end"])):
                rep.产品撞车对数 += 1
                dirty.add(x["团队ID"])
                dirty.add(y["团队ID"])
                rep.findings.append(Finding(
                    "H2", "同撮学生同时段排了两个产品", "·".join(map(str, key)),
                    "%s %s(%s) ✕ %s %s(%s)" % (x[TIME_COL], x["产品"], x["主指导员"],
                                               y[TIME_COL], y["产品"], y["主指导员"])))
    rep.产品撞车团队数 = len(dirty)


def _check_room_clash(df, rep):
    if "指导室" not in df.columns:
        return
    sub = df[df["指导室"].astype(str).str.strip() != ""]
    for key, g in sub.groupby(["段次", "周", "中心", "指导室"]):
        for x, y in combinations(g.to_dict("records"), 2):
            if overlaps((x["_start"], x["_end"]), (y["_start"], y["_end"])):
                rep.教室撞车 += 1
                rep.findings.append(Finding(
                    "H3", "教室同时段撞车", "·".join(map(str, key)),
                    "%s ✕ %s" % (x[TIME_COL], y[TIME_COL])))


def _check_adjacency(df, cfg, rep):
    block = cfg.get("连堂", {}) or {}
    scope = block.get("分组范围") or ["校区", "程度", "团队类型"]
    gap_count = make_gap_counter(cfg["时段"])
    auto_limit, _, why = derive_adjacency_limit(cfg["时段"])
    rep.间隔阈值说明 = why

    for rule in block.get("规则") or []:
        products = rule["产品"]
        allowed = int(rule.get("允许中间隔", 0))
        limit = rule.get("最大间隙_分钟")
        if limit in ("自动", "auto", None):
            limit = auto_limit
        ordered = rule.get("顺序") == "按列表"
        total = loose = tight = 0

        for key, sub in df.groupby(["段次", "周"] + scope):
            picks = {p: sub[sub["产品"] == p] for p in products}
            if any(v.empty for v in picks.values()):
                continue
            for a, b in combinations(products, 2):
                # 同一撮学生里，各取该产品最早的一节来判断
                x = picks[a].nsmallest(1, "_start").iloc[0]
                y = picks[b].nsmallest(1, "_start").iloc[0]
                first, second = (x, y) if x["_start"] <= y["_start"] else (y, x)
                total += 1
                where = "·".join(map(str, key))

                if overlaps((x["_start"], x["_end"]), (y["_start"], y["_end"])):
                    rep.findings.append(Finding(
                        "S1", "%s · 两节撞在同一时段" % rule["名称"], where,
                        "%s %s ✕ %s %s" % (a, x[TIME_COL], b, y[TIME_COL])))
                    continue

                between = gap_count((first["_start"], first["_end"]),
                                    (second["_start"], second["_end"]))
                wait = second["_start"] - first["_end"]
                order_ok = (not ordered) or first["产品"] == products[0]
                pair = "%s %s → %s %s" % (first["产品"], first[TIME_COL],
                                          second["产品"], second[TIME_COL])

                if between <= allowed and order_ok:
                    loose += 1
                    if limit is None or wait <= limit:
                        tight += 1
                    else:
                        rep.findings.append(Finding(
                            "S1", "%s · 中间要等 %d 分钟（超过 %d）"
                            % (rule["名称"], wait, limit), where, pair))
                else:
                    rep.findings.append(Finding(
                        "S1", "%s · 没挨着（中间夹了 %d 节别的课）" % (rule["名称"], between),
                        where, pair))

        rep.连堂.append((rule["名称"], rule.get("强度", "软"), total, loose, tight, limit))


def _check_transfers(df, travel, cfg, rep):
    level = "H4" if (cfg.get("地理", {}) or {}).get("违规级别") == "硬" else "S3"
    gap_count = make_gap_counter(cfg["时段"])
    gaps = []

    for key, sub in df.groupby(["段次", "周", "主指导员"]):
        rep.当日人次 += 1
        rows = sub.sort_values("_start").to_dict("records")
        if sub["中心"].nunique() == 1:
            rep.单中心人次 += 1

        for prev, cur in zip(rows, rows[1:]):
            if prev["中心"] == cur["中心"]:
                continue
            rep.转场次数 += 1
            a, b = prev["中心"], cur["中心"]
            have = cur["_start"] - prev["_end"]
            rep.转场里程 += travel.km(a, b)
            source = travel.source(a, b)
            rep.转场按来源[source] = rep.转场按来源.get(source, 0) + 1

            ok, reason = travel.acceptable(a, b, have)
            if not ok:
                rep.赶不及次数 += 1
                rep.findings.append(Finding(
                    level, reason, "%s %s %s" % key,
                    "%s %s → %s %s（%s）" % (a, prev[TIME_COL], b, cur[TIME_COL],
                                            travel.label(a, b))))

        slots = sorted({(r["_start"], r["_end"]) for r in rows})
        if len(slots) > 1:
            gaps.append(sum(gap_count(a, b) for a, b in zip(slots, slots[1:])))

    rep.空档段数 = sum(gaps)
    rep.有空档人次 = sum(1 for g in gaps if g)
    rep.多节课人次 = len(gaps)


def run(schedule_path, cfg, sheet=None, df=None):
    """跑一遍体检，返回 Report。df 可直接传入已加载的表（GUI 里复用）。"""
    if df is None:
        df = load_schedule(schedule_path, cfg, sheet)

    rep = Report(
        团队数=len(df), 中心数=df["中心"].nunique(), 校区数=df["校区"].nunique(),
        指导员数=df["主指导员"].nunique(),
        未排上行数=df.attrs.get("未排上行数", 0),
        冲突口径="同时段 + " + " + ".join(cfg["冲突口径"]["分组字段"]))

    campus_of = dict(zip(df["中心"], df["校区"]))
    region_of = dict(zip(df["中心"], df["区域"])) if "区域" in df.columns else {}
    coords, explicit = load_geo(cfg)
    travel = Travel(cfg, coords, explicit, campus_of, region_of)

    _check_teacher_clash(df, rep)
    _check_product_clash(df, cfg, rep)
    _check_room_clash(df, rep)
    _check_adjacency(df, cfg, rep)
    _check_transfers(df, travel, cfg, rep)
    rep.用了粗判 = travel.used_fallback
    rep.判定方式 = travel.mode

    load = df.groupby("主指导员").size()
    rep.人均团队 = float(load.mean())
    rep.最多团队 = int(load.max())
    rep.工作量方差 = float(statistics.pvariance(load)) if len(load) > 1 else 0.0

    w = cfg["权重"]
    adj_miss = sum(total - tight for _, _, total, _, tight, _ in rep.连堂)
    rep.罚分 = (w["连堂不相邻"] * adj_miss
                + w["转场时间不够"] * rep.赶不及次数
                + w["每公里转场"] * rep.转场里程
                + w["跨中心一次"] * rep.转场次数
                + w["课表空档一段"] * rep.空档段数
                + w["工作量方差"] * rep.工作量方差)
    return rep
