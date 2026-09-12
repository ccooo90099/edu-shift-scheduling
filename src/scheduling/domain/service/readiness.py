"""数据就绪度检查 —— 顶部常驻告警条的数据来源。

**为什么必须是常驻告警而不是一次性提示**：缺坐标、缺资质配置都**不会报错**，
求解照样出结果，只是悄悄退化。用户会拿到一份看起来正常的排班，
实际上路上时间全是猜的。所以要一直喊到补完为止。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Severity(Enum):
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True)
class ReadinessIssue:
    code: str
    severity: Severity
    summary: str
    #: 不管的后果 —— 说清楚才有人去补
    consequence: str
    affected: tuple[str, ...] = ()
    fix_route: str = ""

    @property
    def count(self) -> int:
        return len(self.affected)


def check_readiness(centers, instructors, calendar) -> list[ReadinessIssue]:
    """返回所有待补数据。空列表 = 一切就绪，告警条隐藏。"""
    issues: list[ReadinessIssue] = []

    missing_coord = [c.name for c in centers if not c.has_coordinate]
    if missing_coord:
        issues.append(ReadinessIssue(
            code="center.coordinate.missing",
            severity=Severity.WARNING,
            summary="%d 个中心还没有坐标" % len(missing_coord),
            consequence="跨中心的路上时间只能按同校区/同区域/跨区域三档粗判，"
                        "「赶不赶得及」基本失效，而且不会报错",
            affected=tuple(missing_coord),
            fix_route="/centers?filter=missing-coordinate"))

    unconfigured = [i.name for i in instructors if not i.is_configured]
    if unconfigured:
        issues.append(ReadinessIssue(
            code="instructor.unconfigured",
            severity=Severity.WARNING,
            summary="%d 位指导员还没配可教产品" % len(unconfigured),
            consequence="资质与可用性约束落空，可能把人排到他去不了的中心",
            affected=tuple(unconfigured),
            fix_route="/instructors?filter=unconfigured"))

    if calendar is None or calendar.is_empty:
        issues.append(ReadinessIssue(
            code="calendar.empty",
            severity=Severity.WARNING,
            summary="还没填学年日历",
            consequence="排班展不开成真实日期，跨批次的指导员撞车查不出来",
            fix_route="/calendar"))

    estimated_rooms = [c.name for c in centers if c.rooms_are_estimated]
    if estimated_rooms:
        issues.append(ReadinessIssue(
            code="center.rooms.estimated",
            severity=Severity.INFO,
            summary="%d 个中心的教室数是从历史并发推算的估计值" % len(estimated_rooms),
            consequence="不等于经过核验的真实场地清单，容量判定可能偏松或偏紧",
            affected=tuple(estimated_rooms),
            fix_route="/centers?filter=estimated-rooms"))

    return issues
