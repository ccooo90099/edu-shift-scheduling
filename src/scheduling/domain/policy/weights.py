"""目标函数权重。

⚠️ 两个历史教训写在这里，别再踩：

1. **加载后必须打印实际生效的权重。** `weights_from()` 是
   `dict(DEFAULT)` 再 `.update(配置)` —— 同名键覆盖，未提供的键保留默认。
   曾经连续三轮调 `跨中心一次`（20→150→800）完全不生效，因为配置文件里
   那个键还写着 20。发现方式是报告里 `跨中心 460 = 23 × 20`。

2. **所有权重读取一律用 `.get()`。** 曾经改键名没同步到体检侧，直接 KeyError
   把报告整个崩掉。
"""
from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_WEIGHTS: dict[str, int] = {
    # —— 降级链，必须满足 排不上 >> 挪期位 > 拆天 > 不连堂 ——
    "排不上团队": 100000,
    "挪到另一期位": 4000,
    "期位与历史不符": 300,
    "连堂未达标": 60,
    # —— 覆盖率 ——
    "年级科目未覆盖": 200,
    # —— 转场 ——
    "转场一次": 800,
    "每公里转场": 6,
    # —— 课表质量 ——
    "课表空档一段": 8,
    "工作量峰值": 30,
    # —— 并发（原 H2 降级而来，按受影响学生数加权）——
    "并发每受影响学生": 12,
    # —— 期位 A 优先（周六更好排）——
    "排在期位B": 20,
    # —— 两个期位都要有班，家长才有得选、老生才换得了 ——
    "单边期位无班": 150,
    # —— 少用几间教室（distinct−1 口径，不是换教室次数）——
    "额外使用教室": 15,
    # —— 修复模式 ——
    "与原排班不同": 0,
}


#: 旧键名 → 新键名。报错时给出改名指引，而不是只说「不认识」。
RENAMED: dict[str, str] = {
    "未排上团队": "排不上团队",
    "跨中心一次": "转场一次",
    "连堂不相邻": "连堂未达标",
    "工作量方差": "工作量峰值",
}


@dataclass
class Weights:
    """生效权重。`effective_report()` 的输出应当打进日志和界面。"""
    values: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    overridden: tuple[str, ...] = ()

    @classmethod
    def from_config(cls, config: dict | None = None, **overrides) -> "Weights":
        merged = dict(DEFAULT_WEIGHTS)
        supplied = dict(config or {})
        supplied.update(overrides)
        unknown = set(supplied) - set(DEFAULT_WEIGHTS)
        if unknown:
            hints = []
            for key in sorted(unknown):
                new_name = RENAMED.get(key)
                hints.append("  %s%s" % (
                    key, " → 现在叫「%s」" % new_name if new_name
                    else "（已废弃，删掉即可）"))
            raise ValueError(
                "配置里有 %d 个权重键对不上：\n%s\n"
                "可用的键：%s\n"
                "—— 之所以直接报错而不是忽略：静默忽略会让你调的权重完全不生效，"
                "这个项目真踩过（连调三轮没反应）。" % (
                    len(unknown), "\n".join(hints),
                    "、".join(sorted(DEFAULT_WEIGHTS))))
        merged.update(supplied)
        return cls(merged, tuple(sorted(supplied)))

    def __getitem__(self, key: str) -> int:
        return self.values.get(key, 0)

    def get(self, key: str, default: int = 0) -> int:
        return self.values.get(key, default)

    def effective_report(self) -> str:
        lines = ["实际生效的权重（★ = 被配置覆盖）："]
        for k, v in self.values.items():
            mark = "★" if k in self.overridden else " "
            lines.append("  %s %-18s %d" % (mark, k, v))
        return "\n".join(lines)
