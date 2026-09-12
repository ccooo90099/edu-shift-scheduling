"""场地容量 —— 同一时刻最多能开几个班。

**粒度不固定，所以做成配置。** 用户原话：「教室数不一定，应该做成配置。」

两层，都可选，同时生效时取更严的：

  ① 中心级：教室数。教室物理上就在某栋楼里，所以这是基础的一层。
  ② 校区级：整个校区的并发上限。有时候真正卡住的不是某栋楼的教室数，
     而是整个校区能同时开的班数（共用的前台、保安、可调度的老师…）。
     百花科学 + 百花文学 加起来可能有 8 间教室，但校区只允许同时开 5 个班。

没配校区上限时只用第①层 —— 不要凭空造一个限制出来。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CapacityPolicy:
    """并发容量。"""
    #: 中心 → 教室数。缺失表示该中心不设中心级限制。
    center_rooms: dict[str, int] = field(default_factory=dict)
    #: 校区 → 同时最多开几个班。缺失表示该校区不设校区级限制。
    campus_caps: dict[str, int] = field(default_factory=dict)

    def center_limit(self, center: str) -> int | None:
        return self.center_rooms.get(center)

    def campus_limit(self, campus: str) -> int | None:
        return self.campus_caps.get(campus)

    def has_any_limit(self, center: str, campus: str) -> bool:
        return (self.center_limit(center) is not None
                or self.campus_limit(campus) is not None)

    def describe(self, center: str, campus: str) -> str:
        """给报告和界面用的人话说明。"""
        parts = []
        room = self.center_limit(center)
        if room is not None:
            parts.append("%s 有 %d 间教室" % (center, room))
        cap = self.campus_limit(campus)
        if cap is not None:
            parts.append("%s 校区同时最多 %d 个班" % (campus, cap))
        if not parts:
            return "没有容量限制"
        return "；".join(parts) + ("（两条都要满足）" if len(parts) > 1 else "")

    @classmethod
    def from_centers(cls, centers, campus_caps=None) -> "CapacityPolicy":
        rooms = {name: c.room_count for name, c in centers.items()
                 if c.room_count > 0}
        return cls(center_rooms=rooms, campus_caps=dict(campus_caps or {}))
