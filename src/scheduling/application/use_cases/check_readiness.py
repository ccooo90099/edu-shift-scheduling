"""用例：检查数据就绪度。

CLI 和网页共用。缺坐标、缺资质都不会让求解报错，只会让它悄悄退化 ——
所以这个检查要在每个页面顶部一直跑。
"""
from __future__ import annotations

from ...domain.service.readiness import check_readiness
from ..dto import ReadinessView


class CheckReadiness:
    def __init__(self, centers, instructors, calendars):
        self._centers = centers
        self._instructors = instructors
        self._calendars = calendars

    def __call__(self) -> list[ReadinessView]:
        issues = check_readiness(
            self._centers.all(), self._instructors.all(), self._calendars.load())
        return [ReadinessView(
            code=i.code, severity=i.severity.value, summary=i.summary,
            consequence=i.consequence, count=i.count, fix_route=i.fix_route)
            for i in issues]
