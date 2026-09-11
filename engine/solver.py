"""排班求解器（CP-SAT）。

按 (段次, 周) 拆成互不相干的子问题分别求解 —— 不同段次的课不会互相冲突，
拆开之后每个子问题两万个变量以内，秒级出解。

决策：每个团队定 (时段, 主指导员)。教室不单独分配，只约束并发数不超过间数。

关于"硬约束"：连堂规则标了「硬」，这里仍然用一个极大的罚分而不是真的硬约束。
因为真硬约束排不下时求解器只会回一句 INFEASIBLE，你不知道是哪几条卡住了；
用极大罚分则一定出解，报告里把违反的条目全列出来，能直接看到问题在哪。
"""
import time
from collections import defaultdict
from dataclasses import dataclass, field

from ortools.sat.python import cp_model

from .slots import derive_adjacency_limit, make_gap_counter, overlaps, parse_slot
from .travel import Travel, load_geo

UNASSIGNED = "未排上"


@dataclass
class SolveResult:
    assignments: dict = field(default_factory=dict)     # 团队ID -> (时段, 主指导员)
    未排上: list = field(default_factory=list)
    连堂未满足: list = field(default_factory=list)       # (学生群, 规则名, 强度)
    状态: str = ""
    罚分: float = 0.0
    分项: dict = field(default_factory=dict)
    用时秒: float = 0.0
    子问题: list = field(default_factory=list)

    @property
    def 可行(self):
        return not self.未排上 and not [x for x in self.连堂未满足 if x[2] == "硬"]


class _GroupModel:
    """一个 (段次, 周) 子问题。"""

    def __init__(self, teams, instructors, rooms, slots, cfg, travel, weights, seed=None):
        self.teams = teams
        self.instructors = instructors
        self.rooms = rooms
        self.slots = sorted(slots, key=lambda s: parse_slot(s)[0])
        self.cfg = cfg
        self.travel = travel
        self.w = weights
        self.seed = seed or {}
        self.m = cp_model.CpModel()
        self.terms = []                    # (名称, 表达式, 权重)

        self.x = {}                        # (团队ID, 时段, 老师) -> BoolVar
        self.unassigned = {}
        self.team_slot = {}                # (团队ID, 时段) -> BoolVar
        self.at = {}                       # (老师, 时段, 中心) -> BoolVar
        self.busy = {}                     # (老师, 时段) -> BoolVar
        self.uses = {}                     # (老师, 中心) -> BoolVar

        self._center_index = {t.团队ID: t.中心 for t in teams}
        self._uses_cache = {}
        self._by_team_slot = defaultdict(list)          # (团队ID, 时段) -> [BoolVar]
        self._by_inst_slot_center = defaultdict(list)   # (老师, 时段, 中心) -> [BoolVar]
        self._by_inst = defaultdict(list)               # 老师 -> [BoolVar]
        self.banned_transfers = 0

    # ── 建模 ──────────────────────────────────────────────────────
    def build(self):
        self._variables()
        self._break_symmetry()
        self._no_double_booking()
        self._one_product_per_slot()
        self._room_capacity()
        self._workload()
        self._travel()
        self._idle_gaps()
        self._adjacency()
        self._stay_close_to_seed()
        self.m.Minimize(sum(expr * weight for _, expr, weight in self.terms))

    def _variables(self):
        by_slot_inst = defaultdict(list)
        for t in self.teams:
            options = []
            for s in self.slots:
                for inst in self.instructors:
                    if not inst.能教(t) or s in inst.不可用时段:
                        continue
                    v = self.m.NewBoolVar("x_%s_%s_%s" % (t.团队ID, s, inst.姓名))
                    self.x[(t.团队ID, s, inst.姓名)] = v
                    options.append(v)
                    by_slot_inst[(inst.姓名, s)].append(v)
                    self._by_team_slot[(t.团队ID, s)].append(v)
                    self._by_inst_slot_center[(inst.姓名, s, t.中心)].append(v)
                    self._by_inst[inst.姓名].append(v)

            none = self.m.NewBoolVar("none_%s" % t.团队ID)
            self.unassigned[t.团队ID] = none
            self.m.AddExactlyOne(options + [none])

            for s in self.slots:
                picks = self._by_team_slot[(t.团队ID, s)]
                ts = self.m.NewBoolVar("ts_%s_%s" % (t.团队ID, s))
                if picks:
                    self.m.Add(sum(picks) == ts)
                else:
                    self.m.Add(ts == 0)
                self.team_slot[(t.团队ID, s)] = ts

        self.by_slot_inst = by_slot_inst
        self.terms.append(("未排上团队", sum(self.unassigned.values()), self.w["未排上团队"]))

    def _break_symmetry(self):
        """完全可互换的平行班，强制按时段顺序排。

        百花 S7 有 4 个编程平行班，除了编号什么都一样 —— 它们之间 4! = 24 种
        排法完全等价。不打破这种对称，求解器会在等价解之间反复打转。
        """
        groups = defaultdict(list)
        for t in self.teams:
            groups[(t.中心, t.程度, t.产品, t.团队类型)].append(t)

        index = {s: i for i, s in enumerate(self.slots)}
        self.slot_index = {}
        for key, members in groups.items():
            if len(members) < 2:
                continue
            ordered = sorted(members, key=lambda t: t.团队ID)
            for t in ordered:
                iv = self.m.NewIntVar(0, len(self.slots), "si_%s" % t.团队ID)
                # 未排上的记成"最后"，不参与顺序约束的实际含义
                self.m.Add(iv == sum(index[s] * self.team_slot[(t.团队ID, s)]
                                     for s in self.slots)
                           + len(self.slots) * self.unassigned[t.团队ID])
                self.slot_index[t.团队ID] = iv
            for a, b in zip(ordered, ordered[1:]):
                self.m.Add(self.slot_index[a.团队ID] <= self.slot_index[b.团队ID])

    def _no_double_booking(self):
        """H1 一个老师同一时间只能带一个团队（含时段重叠的情况）。"""
        for inst in self.instructors:
            for s in self.slots:
                picks = self.by_slot_inst.get((inst.姓名, s), [])
                b = self.m.NewBoolVar("busy_%s_%s" % (inst.姓名, s))
                if picks:
                    self.m.AddAtMostOne(picks)
                    self.m.Add(sum(picks) == b)
                else:
                    self.m.Add(b == 0)
                self.busy[(inst.姓名, s)] = b

            for a, c in self._overlapping_pairs():
                self.m.Add(self.busy[(inst.姓名, a)] + self.busy[(inst.姓名, c)] <= 1)

    def _overlapping_pairs(self):
        out = []
        for i, a in enumerate(self.slots):
            for c in self.slots[i + 1:]:
                if overlaps(parse_slot(a), parse_slot(c)):
                    out.append((a, c))
        return out

    def _one_product_per_slot(self):
        """H2 同时段 + 同校区 + 同程度，只能出现一个产品。"""
        groups = defaultdict(lambda: defaultdict(list))
        for t in self.teams:
            groups[t.冲突组][t.产品].append(t)

        self.used = {}
        for cg, by_product in groups.items():
            if len(by_product) < 2:
                continue
            for s in self.slots:
                flags = []
                for product, members in by_product.items():
                    u = self.m.NewBoolVar("u_%s_%s_%s" % (cg, s, product))
                    picks = [self.team_slot[(t.团队ID, s)] for t in members]
                    self.m.AddMaxEquality(u, picks)
                    self.used[(cg, s, product)] = u
                    flags.append(u)
                self.m.AddAtMostOne(flags)

            # 时段重叠的两个格子，合起来也只能有一个产品。
            # 注意要覆盖两个方向：(p1 在前, p2 在后) 和 (p2 在前, p1 在后)。
            # 只写 p1 < p2 的话反方向没人管，重叠时段就会漏出两个产品。
            for a, c in self._overlapping_pairs():
                for p1 in by_product:
                    for p2 in by_product:
                        if p1 != p2:
                            self.m.Add(self.used[(cg, a, p1)] + self.used[(cg, c, p2)] <= 1)

    def _room_capacity(self):
        """H3 同一中心同一时段的并发团队数不超过教室数。"""
        by_center = defaultdict(list)
        for t in self.teams:
            by_center[t.中心].append(t)
        for center, members in by_center.items():
            limit = self.rooms.get(center)
            if not limit:
                continue
            for s in self.slots:
                self.m.Add(sum(self.team_slot[(t.团队ID, s)] for t in members) <= limit)

    def _workload(self):
        """单人单日上限，以及把最重的那个人压下来。"""
        loads = []
        for inst in self.instructors:
            picks = self._by_inst[inst.姓名]
            if not picks:
                continue
            load = self.m.NewIntVar(0, inst.单日最多节数, "load_%s" % inst.姓名)
            self.m.Add(sum(picks) == load)
            loads.append(load)
        if loads:
            peak = self.m.NewIntVar(0, max(i.单日最多节数 for i in self.instructors), "peak")
            self.m.AddMaxEquality(peak, loads)
            self.terms.append(("工作量峰值", peak, self.w["工作量峰值"]))

    def _travel(self):
        """S2/S3 跑场：赶不及的直接禁止；能赶上的按跑几个中心、多远来扣分。"""
        relevant = defaultdict(set)
        for (tid, _, name) in self.x:
            relevant[name].add(self._center_of(tid))

        banned = 0
        for inst in self.instructors:
            centers = sorted(relevant.get(inst.姓名, ()))
            if len(centers) < 2:
                continue

            for s in self.slots:
                for c in centers:
                    picks = self._by_inst_slot_center[(inst.姓名, s, c)]
                    a = self.m.NewBoolVar("at_%s_%s_%s" % (inst.姓名, s, c))
                    if picks:
                        self.m.Add(sum(picks) == a)
                    else:
                        self.m.Add(a == 0)
                    self.at[(inst.姓名, s, c)] = a

            for c in centers:
                u = self.m.NewBoolVar("uses_%s_%s" % (inst.姓名, c))
                self.m.AddMaxEquality(u, [self.at[(inst.姓名, s, c)] for s in self.slots])
                self.uses[(inst.姓名, c)] = u

            # 赶不及的组合要禁掉。逐对写线性约束的话是 O(中心² × 时段²)，
            # 18 个中心就是每人 5000 条、全体 27 万条 —— 求解器根本收敛不了。
            # 改成表约束：把"这个时段在哪个中心"变成一个整数变量，
            # 每对时段只挂一张允许组合表，一条顶几百条。
            idle = 0
            index = {c: i + 1 for i, c in enumerate(centers)}
            where = {}
            for s in self.slots:
                v = self.m.NewIntVar(0, len(centers), "where_%s_%s" % (inst.姓名, s))
                for c in centers:
                    self.m.Add(v == index[c]).OnlyEnforceIf(self.at[(inst.姓名, s, c)])
                    self.m.Add(v != index[c]).OnlyEnforceIf(self.at[(inst.姓名, s, c)].Not())
                self.m.Add(v == idle).OnlyEnforceIf(self.busy[(inst.姓名, s)].Not())
                where[s] = v

            for i, s1 in enumerate(self.slots):
                for s2 in self.slots[i + 1:]:
                    gap = parse_slot(s2)[0] - parse_slot(s1)[1]
                    if gap < 0:
                        continue
                    allowed = [(idle, idle)]
                    allowed += [(idle, index[c]) for c in centers]
                    allowed += [(index[c], idle) for c in centers]
                    for c1 in centers:
                        for c2 in centers:
                            if c1 == c2 or self.travel.acceptable(c1, c2, gap)[0]:
                                allowed.append((index[c1], index[c2]))
                    self.m.AddAllowedAssignments([where[s1], where[s2]], allowed)
                    banned += len(centers) ** 2 - len(allowed) + 2 * len(centers) + 1

            # 单日最多去几个中心 —— 硬上限。除了贴合现实（原数据里 85% 的老师
            # 当天只在一个中心），它还是最有效的剪枝：不设上限的话转场约束是
            # O(老师 × 时段² × 中心²)，二十几万条，求解器根本收敛不了。
            cap = self.cfg.get("指导员", {}).get("单日最多中心数")
            if cap:
                self.m.Add(sum(self.uses[(inst.姓名, c)] for c in centers) <= int(cap))

            # 只罚"多跑的那几个中心"。按"去过几个"算的话，只去一个也要扣分，
            # 等于给"启用一个老师"加成本，会把课压到少数人头上。
            active = self.m.NewBoolVar("active_%s" % inst.姓名)
            self.m.AddMaxEquality(active, [self.uses[(inst.姓名, c)] for c in centers])
            extra = self.m.NewIntVar(0, len(centers), "extra_%s" % inst.姓名)
            self.m.Add(extra == sum(self.uses[(inst.姓名, c)] for c in centers) - active)
            self.terms.append(("跨中心", extra, self.w["跨中心一次"]))
            for i, c1 in enumerate(centers):
                for c2 in centers[i + 1:]:
                    both = self.m.NewBoolVar("both_%s_%s_%s" % (inst.姓名, c1, c2))
                    self.m.AddMinEquality(both, [self.uses[(inst.姓名, c1)],
                                                 self.uses[(inst.姓名, c2)]])
                    self.terms.append(("转场里程", both,
                                       self.w["每公里转场"] * round(self.travel.km(c1, c2))))
        self.banned_transfers = banned

    def _center_of(self, tid):
        return self._center_index[tid]

    def _idle_gaps(self):
        """S4 老师课表中间的空档。"""
        costs = []
        for inst in self.instructors:
            flags = [self.busy[(inst.姓名, s)] for s in self.slots]
            for k in range(1, len(self.slots) - 1):
                before = self.m.NewBoolVar("bef_%s_%d" % (inst.姓名, k))
                after = self.m.NewBoolVar("aft_%s_%d" % (inst.姓名, k))
                self.m.AddMaxEquality(before, flags[:k])
                self.m.AddMaxEquality(after, flags[k + 1:])
                idle = self.m.NewBoolVar("idle_%s_%d" % (inst.姓名, k))
                self.m.AddBoolAnd([before, after, flags[k].Not()]).OnlyEnforceIf(idle)
                self.m.AddBoolOr([before.Not(), after.Not(), flags[k]]).OnlyEnforceIf(idle.Not())
                costs.append(idle)
        if costs:
            self.terms.append(("课表空档", sum(costs), self.w["课表空档一段"]))

    def _adjacency(self):
        """S1 配置里要连堂的产品，必须落在相接且等待够短的两个时段。"""
        block = self.cfg.get("连堂", {}) or {}
        rules = block.get("规则") or []
        scope = block.get("分组范围") or ["校区", "程度", "团队类型"]
        gap_count = make_gap_counter(self.cfg["时段"])
        auto_limit, _, _ = derive_adjacency_limit(self.cfg["时段"])

        groups = defaultdict(lambda: defaultdict(list))
        for t in self.teams:
            key = tuple(getattr(t, f) for f in scope)
            groups[key][t.产品].append(t)

        self.adjacency_flags = []
        for rule in rules:
            products = rule["产品"]
            limit = rule.get("最大间隙_分钟")
            if limit in ("自动", "auto", None):
                limit = auto_limit
            ordered = rule.get("顺序") == "按列表"
            weight = self.w["连堂不相邻"] * (self.w["硬约束倍数"]
                                             if rule.get("强度") == "硬" else 1)

            for key, by_product in groups.items():
                if any(p not in by_product for p in products):
                    continue
                pairs = []
                for a, b in self._slot_pairs(gap_count, limit, ordered):
                    p = self.m.NewBoolVar("adj")
                    ua = self._group_uses(key, by_product, products[0], a)
                    ub = self._group_uses(key, by_product, products[1], b)
                    self.m.AddBoolAnd([ua, ub]).OnlyEnforceIf(p)
                    pairs.append(p)
                ok = self.m.NewBoolVar("adjok")
                self.m.AddBoolOr(pairs).OnlyEnforceIf(ok)
                self.m.Add(sum(pairs) == 0).OnlyEnforceIf(ok.Not())
                self.terms.append(("连堂未满足", ok.Not(), weight))
                self.adjacency_flags.append((key, rule.get("名称", ""),
                                             rule.get("强度", "软"), ok))

    def _slot_pairs(self, gap_count, limit, ordered):
        """所有"中间不夹课、等待不超限"的时段对。ordered=False 时正反都算。"""
        out = []
        for i, a in enumerate(self.slots):
            for b in self.slots[i + 1:]:
                pa, pb = parse_slot(a), parse_slot(b)
                if pb[0] < pa[1] or gap_count(pa, pb) != 0:
                    continue
                if limit is not None and pb[0] - pa[1] > limit:
                    continue
                out.append((a, b))
                if not ordered:
                    out.append((b, a))
        return out

    def _group_uses(self, key, by_product, product, slot):
        cached = self._uses_cache.get((key, product, slot))
        if cached is not None:
            return cached
        u = self.m.NewBoolVar("gu")
        self.m.AddMaxEquality(u, [self.team_slot[(t.团队ID, slot)]
                                  for t in by_product[product]])
        self._uses_cache[(key, product, slot)] = u
        return u

    def add_hint(self):
        """用原排班当热启动。可行解不必最优，给个起点就能省很多搜索。"""
        if not self.seed:
            return
        hinted = 0
        for t in self.teams:
            original = self.seed.get(t.团队ID)
            if not original:
                continue
            key = (t.团队ID, original[0], original[1])
            if key in self.x:
                self.m.AddHint(self.x[key], 1)
                hinted += 1
        return hinted

    def _stay_close_to_seed(self):
        """修复模式：和原排班不一样的地方要扣分，改动越少越好。"""
        if not self.seed or not self.w.get("与原排班不同"):
            return
        same = []
        for t in self.teams:
            original = self.seed.get(t.团队ID)
            if not original:
                continue
            slot, name = original
            key = (t.团队ID, slot, name)
            if key in self.x:
                same.append(self.x[key])
        if same:
            self.terms.append(("与原排班不同",
                               len(same) - sum(same), self.w["与原排班不同"]))


# 权重是业务取舍，不是技术参数。这组默认值对着原始数据调过，关键是两者的比例：
#
#   一条硬连堂没满足 = 3000 分   跨一个中心 = 800 分
#
# 比例约 3.75:1 —— 为了救一条硬连堂可以调动一个老师，但不会为此满城调人。
# 之前是 12000 : 150（80:1），求解器算出来 31 次转场：段次3 只有 4 个时段、
# 间隔 20/90/20 分钟，只有中午那档来得及跨中心，31 次等于 56% 的老师
# 每个上课日中午横穿城市。手工排班是 8 次，85% 的老师当天只在一个中心。
DEFAULT_WEIGHTS = {
    "未排上团队": 100000,
    "连堂不相邻": 60,
    "硬约束倍数": 50,         # 标了「硬」的连堂规则，罚分放大这么多倍 → 3000
    "跨中心一次": 800,        # 老师当天多跑一个中心的代价
    "每公里转场": 6,
    "课表空档一段": 8,
    "工作量峰值": 30,
    "与原排班不同": 0,        # 修复模式下调高
}


def weights_from(cfg, overrides=None):
    w = dict(DEFAULT_WEIGHTS)
    w.update(cfg.get("权重") or {})
    w.update(overrides or {})
    w.setdefault("工作量峰值", w.get("工作量方差", 30))
    return w


def solve(teams, instructors, rooms, cfg, *, seed=None, time_limit=60,
          workers=8, weights=None, log=None):
    """按 (段次, 周) 拆开分别求解，汇总成一个结果。

    seed: {团队ID: (时段, 主指导员)}，给了就是修复模式 —— 在原排班上做最小改动。
    """
    started = time.time()
    w = weights_from(cfg, weights)
    campus_of = {t.中心: t.校区 for t in teams}
    region_of = {t.中心: t.区域 for t in teams if t.区域}
    coords, table = load_geo(cfg)
    travel = Travel(cfg, coords, table, campus_of, region_of)

    result = SolveResult()
    groups = defaultdict(list)
    for t in teams:
        groups[(t.段次, t.周)].append(t)

    for key in sorted(groups):
        members = groups[key]
        slots = cfg["时段"]
        model = _GroupModel(members, list(instructors.values()), rooms,
                            slots, cfg, travel, w, seed)
        model._uses_cache = {}
        model.build()
        model.add_hint()

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = float(time_limit)
        solver.parameters.num_search_workers = int(workers)
        status = solver.Solve(model.m)
        name = solver.StatusName(status)

        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            result.未排上.extend(t.团队ID for t in members)
            result.子问题.append({"段次周": key, "团队数": len(members), "状态": name})
            if log:
                log("%s %s：%s，%d 个团队没排上" % (key[0], key[1], name, len(members)))
            continue

        placed = 0
        for t in members:
            if solver.Value(model.unassigned[t.团队ID]):
                result.未排上.append(t.团队ID)
                continue
            for (tid, s, inst), v in model.x.items():
                if tid == t.团队ID and solver.Value(v):
                    result.assignments[t.团队ID] = (s, inst)
                    placed += 1
                    break

        for group_key, rule_name, strength, ok in model.adjacency_flags:
            if not solver.Value(ok):
                result.连堂未满足.append((group_key, rule_name, strength))

        result.罚分 += solver.ObjectiveValue()
        for label, expr, weight in model.terms:
            if weight:
                result.分项[label] = result.分项.get(label, 0) + solver.Value(expr) * weight
        result.子问题.append({"段次周": key, "团队数": len(members), "状态": name,
                              "排上": placed, "禁止的转场": model.banned_transfers,
                              "用时秒": round(solver.WallTime(), 2)})
        if log:
            log("%s %s：%s，%d/%d 排上，用时 %.1fs"
                % (key[0], key[1], name, placed, len(members), solver.WallTime()))

    result.状态 = "全部排上" if not result.未排上 else "有 %d 个没排上" % len(result.未排上)
    result.用时秒 = round(time.time() - started, 2)
    return result
