"""场地 —— 中心、校区、教室。

**教室是实体，不是一个计数。** 只知道「有几间」就无法判断两个班是不是
同一间，S11（少用几间教室）也就没有落点，座位数字段更是死的。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .timeslot import TimeSlot


class Datum(Enum):
    """坐标系。国内三家地图各不相同，混用会凭空差出几百米。"""
    WGS84 = "wgs84"     # 国际标准：天地图、OpenStreetMap
    GCJ02 = "gcj02"     # 火星坐标：高德、腾讯
    BD09 = "bd09"       # 百度：在 GCJ-02 上再偏一次，**不是 GCJ-02**


#: 地图来源 → 坐标系。让用户选「从哪个地图复制的」（他知道），
#: 而不是选「坐标系」（他不该需要知道）。
MAP_SOURCE_DATUM = {
    "高德": Datum.GCJ02,
    "腾讯": Datum.GCJ02,
    "百度": Datum.BD09,
    "天地图": Datum.WGS84,
    "OpenStreetMap": Datum.WGS84,
}


@dataclass(frozen=True)
class Coordinate:
    """一个点。datum 必须显式给出 —— 未知来源不能静默当作 WGS-84。"""
    longitude: float
    latitude: float
    datum: Datum

    @classmethod
    def from_map_source(cls, longitude, latitude, source: str) -> "Coordinate":
        try:
            return cls(longitude, latitude, MAP_SOURCE_DATUM[source])
        except KeyError:
            raise ValueError(
                "未知地图来源：%r。支持：%s。"
                "不能猜坐标系 —— 猜错会让距离静默偏差几百米。"
                % (source, "、".join(MAP_SOURCE_DATUM))) from None


@dataclass(frozen=True)
class Room:
    """一间教室。身份由 (中心, 教室ID) 确定。"""
    center: str
    room_id: str
    seats: int = 0
    #: 该教室不可用的时段。空 = 全天可用。
    unavailable: frozenset[TimeSlot] = frozenset()

    def can_hold(self, headcount: int) -> bool:
        return self.seats <= 0 or headcount <= self.seats

    def is_available_at(self, slot: TimeSlot) -> bool:
        return slot not in self.unavailable


@dataclass
class Center:
    """一个中心。中心 ≠ 校区：百花科学与百花文学是同一校区的两栋楼。"""
    name: str
    campus: str
    region: str = ""
    address: str = ""
    coordinate: Coordinate | None = None
    #: 定位依据 —— 命中的是哪种问法，方便逐条核对
    located_by: str = ""
    rooms: list[Room] = field(default_factory=list)
    #: 教室数为估计值（由历史并发峰值推出）而非后台填的实数时为 True。
    #: 界面上要标出来 —— 估计值不等于经过核验的真实场地清单。
    rooms_are_estimated: bool = False

    @property
    def room_count(self) -> int:
        return len(self.rooms)

    def set_room_count(self, count: int, *, estimated: bool = False) -> None:
        """把教室数设成 count。

        后台直接填的数是**实数**（`estimated=False`），会覆盖掉之前从
        历史并发峰值推出来的估计值 —— 人填的比推的可信。

        多退少补：已有的教室保留（可能带座位数和不可用时段），
        不够的补占位，多出来的从尾部去掉。
        """
        if count < 0:
            raise ValueError("教室数不能为负")
        keep = self.rooms[:count]
        for i in range(len(keep), count):
            keep.append(Room(self.name, "R%d" % (i + 1)))
        self.rooms = keep
        self.rooms_are_estimated = estimated

    @property
    def has_coordinate(self) -> bool:
        return self.coordinate is not None

    @staticmethod
    def campus_of(center_name: str) -> str:
        """中心名去掉「科学」「文学」后缀就是校区名。"""
        for suffix in ("科学", "文学"):
            if center_name.endswith(suffix):
                return center_name[: -len(suffix)]
        return center_name
