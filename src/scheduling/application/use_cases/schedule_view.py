"""按日期看排班 —— 今天 / 本周 / 本月 有哪些课。

排班的结果是「期位 + 时段」，不是日期。要变成日历上的课，得靠
**学年日历**把期位展开成真实上课日：

    期位 A + 学年日历里 A 的上课日 = 这些天的这个时段有这节课

**没填日历就展不开。** 这时候不该假装能显示 —— 直接说明缺什么、
去哪儿补，比给一张空表强。
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from ...domain.model.period import Period

WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


@dataclass
class Lesson:
    """某一天某个时段的一节课。"""
    day: date
    slot: str
    slot_start: int
    campus: str
    center: str
    grade: str
    subject: str
    tier: str
    instructor: str
    room: str
    period: str

    @property
    def label(self) -> str:
        return "%s/%s/%s/%s" % (self.grade, self.tier, self.subject[:2],
                                self.instructor or "?")


@dataclass
class DayView:
    day: date
    lessons: list[Lesson] = field(default_factory=list)

    @property
    def weekday(self) -> str:
        return WEEKDAYS[self.day.weekday()]

    @property
    def is_today(self) -> bool:
        return self.day == date.today()

    @property
    def slots(self) -> list[str]:
        return sorted({l.slot for l in self.lessons},
                      key=lambda s: next(x.slot_start for x in self.lessons
                                         if x.slot == s))

    def by_campus(self) -> dict:
        out: dict[str, dict[str, list[Lesson]]] = defaultdict(
            lambda: defaultdict(list))
        for l in self.lessons:
            out[l.campus][l.slot].append(l)
        return {k: dict(v) for k, v in sorted(out.items())}

    @property
    def count(self) -> int:
        return len(self.lessons)


RANGES = {
    "day": "今天",
    "week": "本周",
    "month": "本月",
}


def date_range(scope: str, anchor: date | None = None) -> tuple[date, date]:
    today = anchor or date.today()
    if scope == "day":
        return today, today
    if scope == "week":
        start = today - timedelta(days=today.weekday())
        return start, start + timedelta(days=6)
    first = today.replace(day=1)
    nxt = (first + timedelta(days=32)).replace(day=1)
    return first, nxt - timedelta(days=1)


class ScheduleView:
    """把一份求解结果 + 学年日历，变成「哪天有哪些课」。"""

    def __init__(self, calendar):
        self._calendar = calendar

    def teaching_days(self) -> dict[Period, set[date]]:
        out: dict[Period, set[date]] = {Period.A: set(), Period.B: set()}
        for batch in self._calendar:
            for period in (Period.A, Period.B):
                out[period].update(batch.dates_of(period))
        return out

    def days_in(self, result: dict, start: date, end: date) -> list[DayView]:
        """区间内每一天有哪些课。没课的天不返回。"""
        mapping = self.teaching_days()
        by_day: dict[date, list[Lesson]] = defaultdict(list)

        for t in result.get("teams", []):
            if not t.get("placed") or not t.get("period"):
                continue
            period = Period(t["period"])
            for day in mapping.get(period, ()):
                if not (start <= day <= end):
                    continue
                by_day[day].append(Lesson(
                    day=day, slot=t.get("slot") or "",
                    slot_start=t.get("slot_start") or 0,
                    campus=t.get("campus") or "", center=t.get("center") or "",
                    grade=t.get("grade") or "", subject=t.get("subject") or "",
                    tier=t.get("tier") or "", instructor=t.get("instructor") or "",
                    room=t.get("room") or "", period=t["period"]))

        return [DayView(day=d, lessons=sorted(by_day[d],
                                              key=lambda l: (l.slot_start, l.campus)))
                for d in sorted(by_day)]

    def why_empty(self, result) -> str | None:
        """展不开的时候说明缺什么 —— 空表最没用。"""
        if result is None:
            return "还没有排班结果。先跑一次排班。"
        if not any(t.get("placed") for t in result.get("teams", [])):
            return "这次排班一个团队都没排上，没有课可展示。"
        if self._calendar is None or self._calendar.is_empty:
            return ("还没填学年日历。排班的结果是「期位 + 时段」，"
                    "要靠日历把期位展开成真实上课日才能按天看。")
        if not any(self.teaching_days().values()):
            return "学年日历里没有填任何上课日，展不开成日期。"
        return None
