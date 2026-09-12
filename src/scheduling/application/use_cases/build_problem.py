"""用例：从一份明细表 + 配置搭出 SchedulingProblem。

CLI 与网页共用这一条装配路径 —— 两边各搭一遍是口径分叉的温床。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yaml

from ...domain.model.instructor import Instructor
from ...domain.model.period import Period, Season
from ...domain.model.timetable import Timetable
from ...domain.policy.golden_hours import DEFAULT_GOLDEN, GoldenHoursPolicy
from ...domain.policy.weights import Weights
from ...domain.model.timeslot import TimeSlot
from ...domain.service.scheduling_problem import SchedulingProblem
from ...infrastructure.spreadsheet.ingest import derive_centers, derive_teams

DEFAULT_SLOTS = ["08:10-10:10", "10:30-12:30", "14:00-16:00",
                 "16:20-18:20", "18:30-20:30"]
#: 春秋季周五只开晚上一档
FRIDAY_SLOTS = ["18:30-20:30"]


@dataclass
class BuildProblem:
    """把 xlsx + yaml 变成一个可求解的问题。"""

    def load_config(self, path) -> dict:
        if not path or not Path(path).exists():
            return {}
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def timetables(self, config: dict, season: Season) -> dict[Period, Timetable]:
        """期位 → 时段表。

        配置可按期位分别给，缺省时两个期位同表。春秋季周五只开一档
        就靠这里表达 —— 不是在代码里写死星期。
        """
        raw = config.get("时段") or {}
        if isinstance(raw, list):
            table = Timetable(raw or DEFAULT_SLOTS)
            return {Period.A: table, Period.B: table}
        out = {}
        for period in (Period.A, Period.B):
            slots = raw.get(period.value) or raw.get(period.label(season))
            out[period] = Timetable(slots or DEFAULT_SLOTS)
        return out

    def golden(self, config: dict) -> GoldenHoursPolicy:
        raw = config.get("黄金时段") or list(DEFAULT_GOLDEN)
        promo = (config.get("促销班") or {}).get("允许占黄金时段", False)
        return GoldenHoursPolicy(
            golden=frozenset(TimeSlot.parse(s) for s in raw),
            promotional_may_use_golden=bool(promo))

    def instructors_from(self, df: pd.DataFrame, teams, repo=None):
        """有配置就用配置；没有就从历史排班反推一个能跑起来的默认池，
        并**标注它是反推的** —— 不能让人以为资质经过核对。"""
        if repo is not None:
            configured = {i.name: i for i in repo.all() if i.is_configured}
            if configured:
                return configured
        pool: dict[str, Instructor] = {}
        if "主指导员" not in df:
            return pool
        by_name: dict[str, set] = {}
        centers: dict[str, set] = {}
        for t, raw in zip(teams, df.itertuples()):
            name = str(getattr(raw, "主指导员", "") or "").strip()
            if not name:
                continue
            by_name.setdefault(name, set()).add(t.product)
            centers.setdefault(name, set()).add(t.center)
        for name, products in by_name.items():
            pool[name] = Instructor(name=name, teachable=products,
                                    allowed_centers=centers.get(name, set()))
        return pool

    def __call__(self, xlsx, config_path=None, *, season=Season.寒暑假,
                 centers_repo=None, instructors_repo=None,
                 calendar_repo=None) -> SchedulingProblem:
        config = self.load_config(config_path)
        df = pd.read_excel(xlsx)
        df = df.map(lambda v: v.strip() if isinstance(v, str) else v)

        teams = derive_teams(df)
        centers = derive_centers(df)
        if centers_repo is not None:
            for saved in centers_repo.all():
                if saved.name in centers:
                    # 已录入的坐标与真实教室清单优先于从明细反推的
                    centers[saved.name] = saved
        instructors = self.instructors_from(df, teams, instructors_repo)

        return SchedulingProblem(
            season=season, teams=teams, instructors=instructors,
            centers=centers, timetables=self.timetables(config, season),
            calendar=calendar_repo.load() if calendar_repo else None,
            weights=Weights.from_config(config.get("权重")),
            golden=self.golden(config))
