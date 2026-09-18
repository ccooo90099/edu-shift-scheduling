"""种子数据 —— 给 demo 用。

免费的 PaaS 大多**重启就清空文件系统**，SQLite 一起没。每次醒来看到一个
空系统，demo 就没法看了。所以启动时如果库是空的，灌一份模拟数据进去。

数据来自 `demo_dataset` —— 结构照着真实那份排班表来
（文学楼只上文学美育、S7 不开物理化学、指导员以单产品为主），
**名字全是编的**。真实门店信息与 106 位指导员姓名一路没进过仓库，这里不破例。
"""
from __future__ import annotations

from datetime import date

from ...domain.model.academic_calendar import AcademicCalendar, Batch
from ...domain.model.period import Period, Season
from .demo_dataset import DemoDataset


class SeedDemo:
    """库是空的就灌一份模拟数据；已有数据就什么都不做。"""

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

        data = DemoDataset()
        centers = data.centers()
        for c in centers:
            self._centers.save(c)
        self._instructors.save_many(data.instructors(centers))

        self._calendars.save(AcademicCalendar([
            Batch("示例·暑假一期", Season.寒暑假,
                  date(2026, 7, 6), date(2026, 7, 16),
                  {Period.A: [date(2026, 7, 6 + i) for i in range(8)]}),
            Batch("示例·暑假二期", Season.寒暑假,
                  date(2026, 7, 20), date(2026, 7, 30),
                  {Period.B: [date(2026, 7, 20 + i) for i in range(8)]}),
        ]))
        return True
