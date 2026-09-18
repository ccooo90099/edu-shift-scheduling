"""模拟数据集 —— 打开就能看结果，不用自己准备文件。

**结构照着真实那份表来，名字全是编的。**

真实表的骨架（`docs/业务需求.md` 里复算过的）：

| 维度 | 真实 | 这里 |
|---|---|---|
| 区域 | 4 个 | 4 个，名字沿用（区域名不算敏感信息） |
| 中心 | 30 个，落在 20 个校区 | 12 个，落在 8 个校区 |
| 科学/文学 | 文学中心**只上**文学美育（26/26 行） | 一样，这条硬约束保留 |
| 程度 | S7 / S8 / S9 | 一样 |
| 产品 | 5 个，S8 起有物理、S9 起有化学 | 一样 |
| 团队类型 | LI/LE/BO/CX/ZY | 一样 |
| 指导员 | 106 人，103 人只教 1 个产品 | 28 人，同样以单产品为主 |
| 团队 | 段次3 有 106 个 | 约 70 个 |
| 人数 | 均值 15.9，容量 24 | 12–22 随机 |

**规模是砍过的。** 真实的 106 个团队 × 55 位老师在 Render 免费档
（512MB、共享 CPU）上求解会很吃力，demo 要的是「点开就看到结果」，
不是压测。要跑真实规模，上传自己的表。
"""
from __future__ import annotations

import random
from dataclasses import dataclass

import pandas as pd

from ...domain.model.venue import Center

REGIONS = ["宝安南山区", "福田区", "龙华区", "罗湖龙岗区"]

#: (校区名, 区域, 有没有文学楼, 科学楼教室数)
CAMPUSES = [
    ("示范一", "福田区",     True,  4),
    ("示范二", "福田区",     False, 3),
    ("示范三", "宝安南山区", True,  4),
    ("示范四", "宝安南山区", False, 3),
    ("示范五", "龙华区",     False, 3),
    ("示范六", "龙华区",     True,  2),
    ("示范七", "罗湖龙岗区", False, 3),
    ("示范八", "罗湖龙岗区", False, 2),
]

#: 深圳市内的点，随手取的，不对应任何真实门店
REGION_ANCHOR = {
    "福田区":     (114.055, 22.541),
    "宝安南山区": (113.925, 22.533),
    "龙华区":     (114.035, 22.660),
    "罗湖龙岗区": (114.125, 22.556),
}

TIERS = ["LI", "LE", "BO", "CX", "ZY"]
GRADES = ["S7", "S8", "S9"]
#: 年级 → 能开的产品。S7 没有物理化学，这是硬约束。
BY_GRADE = {
    "S7": ["编程理论", "双语文化", "文学美育"],
    "S8": ["编程理论", "双语文化", "文学美育", "躬行实践"],
    "S9": ["编程理论", "双语文化", "文学美育", "躬行实践", "溯源"],
}
LITERATURE_ONLY = "文学美育"


@dataclass
class DemoDataset:
    """生成一份模拟的团队清单，以及配套的中心与指导员。"""
    seed: int = 20260918

    def centers(self) -> list[Center]:
        """中心。文学楼只上文学美育 —— 这条真实约束保留。"""
        rng = random.Random(self.seed)
        out = []
        for campus, region, has_lit, rooms in CAMPUSES:
            base_lon, base_lat = REGION_ANCHOR[region]
            for suffix, n in ([("科学", rooms)] + ([("文学", 2)] if has_lit else [])):
                name = campus + suffix
                c = Center(
                    name=name, campus=campus, region=region,
                    address="深圳市%s（示例地址，非真实门店）" % region,
                    located_by="示例数据")
                from ...domain.model.venue import Coordinate, Datum
                c.coordinate = Coordinate(
                    round(base_lon + rng.uniform(-.02, .02), 6),
                    round(base_lat + rng.uniform(-.02, .02), 6), Datum.WGS84)
                c.set_room_count(n, estimated=False)
                out.append(c)
        return out

    def instructors(self, centers):
        """指导员。真实表里 106 人中 103 人只教 1 个产品，
        唯一的跨产品组合是「溯源 + 躬行实践」—— 这个分布照搬。"""
        from ...domain.model.curriculum import product_of
        from ...domain.model.instructor import Instructor
        rng = random.Random(self.seed + 1)
        by_region: dict[str, list[str]] = {}
        for c in centers:
            by_region.setdefault(c.region, []).append(c.name)
        lit = [c.name for c in centers if c.name.endswith("文学")]
        sci = [c.name for c in centers if c.name.endswith("科学")]

        out, n = [], 0
        for product, count in [("编程理论", 8), ("双语文化", 7),
                               ("文学美育", 6), ("躬行实践", 3)]:
            for _ in range(count):
                n += 1
                pool = (lit + sci) if product == LITERATURE_ONLY else sci
                region = rng.choice(REGIONS)
                near = [x for x in by_region[region] if x in pool] or pool
                out.append(Instructor(
                    name="示教%02d" % n, teachable={product_of(product)},
                    allowed_centers=set(rng.sample(near, min(3, len(near)))),
                    max_sessions_per_day=4))
        # 那 3 位跨产品的
        for _ in range(4):
            n += 1
            out.append(Instructor(
                name="示教%02d" % n,
                teachable={product_of("溯源"), product_of("躬行实践")},
                allowed_centers=set(rng.sample(sci, min(4, len(sci)))),
                max_sessions_per_day=4))
        return out

    def teams_frame(self, centers) -> pd.DataFrame:
        """团队清单，列名和真实导出表一致，所以能直接当输入喂进去。"""
        rng = random.Random(self.seed + 2)
        rows = []
        for c in centers:
            is_lit = c.name.endswith("文学")
            for grade in GRADES:
                products = ([LITERATURE_ONLY] if is_lit else BY_GRADE[grade])
                for product in products:
                    if not is_lit and rng.random() < 0.45:
                        continue            # 不是每个中心每个年级都开满
                    for tier in rng.sample(TIERS, rng.choice([1, 1, 2])):
                        rows.append({
                            "团队ID": "D%04d" % (len(rows) + 1),
                            "段次": "段次1", "周": "星期六",
                            "区域": c.region, "中心": c.name,
                            "程度": grade, "产品": product, "团队类型": tier,
                            "团队名称": "%s%s%s1" % (grade, tier, product[:2]),
                            "首次服务时间": "", "主指导员": "",
                            "指导室": "", "是否促销": "否",
                            "人数": rng.randint(12, 22),
                        })
        return pd.DataFrame(rows)

    def write(self, path) -> tuple[int, int, int]:
        """写出 xlsx，返回 (中心数, 指导员数, 团队数)。"""
        centers = self.centers()
        df = self.teams_frame(centers)
        df.to_excel(path, index=False)
        return len(centers), len(self.instructors(centers)), len(df)
