"""人群与报读组合。

⚠️ 这里有一个曾经写错、并且很容易再写错的地方：

  **「人群」不等于「同一批人」，也不等于「按年级该上的全部科目」。**

同校区、同程度、同层级的学生是**同类人群**，但他们报的科目并不一样：
有人只报数学+物理，有人只报一科。如果拿年级去推「S9 就该上五门」，
等于把已经降级掉的 H2 从后门放回来 —— 那条约束当初正是因为
「不是所有学生都读全科」才降级的。

所以判定单位是**报读组合**，不是人群，也不是单个团队。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .curriculum import Grade, Product, Tier, products_for_grade


@dataclass(frozen=True)
class CohortKey:
    """人群标识 —— 只表示「同类人群」，不表示「同一批人」。

    和 H2 的冲突口径共用同一个 key，避免两处口径漂移。
    """
    campus: str
    grade: Grade
    tier: Tier

    def __str__(self):
        return "%s/%s/%s" % (self.campus, self.grade.value, self.tier.value)


@dataclass(frozen=True)
class EnrollmentCombination:
    """一个报读组合：这些学生报了这几科，大约这么多人。

    人数是**滚动估计值**，不是名册。每季每周都在变，还有请假。
    目标函数不该为了几个人的差异去牺牲结构性的好排法。
    """
    products: frozenset[Product]
    estimated_headcount: int

    def __post_init__(self):
        if not self.products:
            raise ValueError("报读组合至少要有一个产品")
        if self.estimated_headcount < 0:
            raise ValueError("人数不能为负")

    def includes(self, *products: Product) -> bool:
        return all(p in self.products for p in products)

    @property
    def size(self) -> int:
        return len(self.products)


@dataclass
class Cohort:
    """一个人群及其下的报读组合。"""
    key: CohortKey
    combinations: list[EnrollmentCombination] = field(default_factory=list)
    #: 组合数据缺失时为 True —— 报告里必须标注，不能让读者以为这是实测
    is_estimated: bool = False

    @property
    def available_products(self) -> tuple[Product, ...]:
        """这个年级**能开**哪些产品。只用于硬约束和覆盖率，
        **不代表**任何一个学生报了这么多科。"""
        return products_for_grade(self.key.grade)

    def headcount_taking_both(self, a: Product, b: Product) -> int:
        """同时报了这两科的估计人数 —— S8 并发惩罚和连堂优先级的依据。"""
        return sum(c.estimated_headcount for c in self.combinations
                   if c.includes(a, b))

    def pair_weights(self) -> dict[frozenset[Product], int]:
        """所有产品对的同报人数，供连堂优先级排序。"""
        weights: dict[frozenset[Product], int] = {}
        for combo in self.combinations:
            items = sorted(combo.products, key=lambda p: p.name)
            for i, a in enumerate(items):
                for b in items[i + 1:]:
                    pair = frozenset((a, b))
                    weights[pair] = weights.get(pair, 0) + combo.estimated_headcount
        return weights

    @property
    def total_headcount(self) -> int:
        return sum(c.estimated_headcount for c in self.combinations)


#: 没有报读组合数据时的默认配对优先级（从高到低）。
#: 只在 Cohort.is_estimated 为真时使用，且报告必须标注「按默认序近似」。
DEFAULT_PAIR_ORDER: tuple[tuple[str, str], ...] = (
    ("编程理论", "文学美育"),   # 数学 + 语文
    ("编程理论", "双语文化"),   # 数学 + 英语
    ("文学美育", "双语文化"),   # 语文 + 英语
)
