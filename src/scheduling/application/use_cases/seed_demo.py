"""种子数据 —— 给 demo 用。

免费的 PaaS 大多**重启就清空文件系统**，SQLite 一起没。每次醒来看到一个
空系统，demo 就没法看了。所以启动时如果库是空的，灌一份假数据进去。

⚠️ **全是编的。** 中心名、地址、指导员姓名都不是真的 —— 真实的门店信息
和 106 位指导员姓名一路都没进过仓库，这里也不会破例。
"""
from __future__ import annotations

from datetime import date

from ...domain.model.academic_calendar import AcademicCalendar, Batch
from ...domain.model.curriculum import product_of
from ...domain.model.instructor import Instructor
from ...domain.model.period import Period, Season
from ...domain.model.timeslot import TimeSlot
from ...domain.model.venue import Center, Coordinate, Datum, Room

#: 编的中心。坐标是深圳市内随手取的点，不对应任何真实门店。
DEMO_CENTERS = [
    # 名称,        校区,   区域,         经度,      纬度,    教室数
    ("示例甲科学", "示例甲", "福田区",     114.0579, 22.5431, 4),
    ("示例甲文学", "示例甲", "福田区",     114.0585, 22.5440, 2),
    ("示例乙科学", "示例乙", "南山区",     113.9308, 22.5330, 3),
    ("示例丙科学", "示例丙", "罗湖区",     114.1230, 22.5480, 3),
    ("示例丁科学", "示例丁", "宝安区",     113.8830, 22.5540, 2),
]

DEMO_ADJACENCY = {"福田区": ["南山区", "罗湖区"], "南山区": ["宝安区"]}

#: 编的指导员。「老师A」这种代号，不是任何真人。
DEMO_INSTRUCTORS = [
    ("老师A", ["编程理论"], ["示例甲科学", "示例乙科学"]),
    ("老师B", ["双语文化"], ["示例甲科学"]),
    ("老师C", ["文学美育"], ["示例甲文学", "示例丙科学"]),
    ("老师D", ["编程理论", "躬行实践"], []),
    ("老师E", ["躬行实践", "溯源"], ["示例乙科学", "示例丁科学"]),
    ("老师F", ["双语文化"], []),
    ("老师G", ["文学美育"], ["示例丁科学"]),
]


class SeedDemo:
    """库是空的就灌一份假数据；已有数据就什么都不做。"""

    def __init__(self, centers, instructors, calendars):
        self._centers = centers
        self._instructors = instructors
        self._calendars = calendars

    def is_empty(self) -> bool:
        return not self._centers.all() and not self._instructors.all()

    def __call__(self, force: bool = False) -> bool:
        """灌了返回 True，跳过返回 False。"""
        if not force and not self.is_empty():
            return False

        for name, campus, region, lon, lat, rooms in DEMO_CENTERS:
            c = Center(name=name, campus=campus, region=region,
                       address="深圳市%s（示例地址，非真实门店）" % region,
                       coordinate=Coordinate(lon, lat, Datum.WGS84),
                       located_by="示例数据")
            c.set_room_count(rooms, estimated=False)
            self._centers.save(c)

        self._instructors.save_many([
            Instructor(name=name,
                       teachable={product_of(p) for p in products},
                       allowed_centers=set(centers),
                       unavailable_slots=({TimeSlot.parse("18:30-20:30")}
                                          if name in ("老师C", "老师F") else set()))
            for name, products, centers in DEMO_INSTRUCTORS])

        self._calendars.save(AcademicCalendar([
            Batch("示例·暑假一期", Season.寒暑假,
                  date(2026, 7, 6), date(2026, 7, 16),
                  {Period.A: [date(2026, 7, 6 + i) for i in range(8)]}),
            Batch("示例·暑假二期", Season.寒暑假,
                  date(2026, 7, 20), date(2026, 7, 30),
                  {Period.B: [date(2026, 7, 20 + i) for i in range(8)]}),
        ]))
        return True
