"""课程体系 —— 产品、程度、层级，以及它们之间的规则。

「产品」是机构的内部叫法，排课逻辑上就是科目。这层映射是业务语言的核心，
写死在这里而不是配置里 —— 它不是参数，是这门生意本身。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Grade(Enum):
    """程度 = 年级。一个学生只属于一个程度，跨科目不变，
    所以它是判定「同一撮学生」的字段。"""
    S7 = "S7"
    S8 = "S8"
    S9 = "S9"

    @property
    def label(self) -> str:
        return {"S7": "初一", "S8": "初二", "S9": "初三"}[self.value]

    @property
    def rank(self) -> int:
        return int(self.value[1:])


class Subject(Enum):
    """科目 —— 学生和家长口中的叫法。"""
    数学 = "数学"
    英语 = "英语"
    语文 = "语文"
    物理 = "物理"
    化学 = "化学"


@dataclass(frozen=True)
class Product:
    """产品 —— 机构内部叫法，一一对应一个科目。"""
    name: str
    subject: Subject
    opens_from: Grade

    def available_to(self, grade: Grade) -> bool:
        return grade.rank >= self.opens_from.rank


#: 产品 ↔ 科目 ↔ 起始年级。初一语数英，初二加物理，初三加化学。
CATALOG: tuple[Product, ...] = (
    Product("编程理论", Subject.数学, Grade.S7),
    Product("双语文化", Subject.英语, Grade.S7),
    Product("文学美育", Subject.语文, Grade.S7),
    Product("躬行实践", Subject.物理, Grade.S8),
    Product("溯源",     Subject.化学, Grade.S9),
)

_BY_NAME = {p.name: p for p in CATALOG}
_BY_SUBJECT = {p.subject: p for p in CATALOG}


def product_of(name: str) -> Product:
    try:
        return _BY_NAME[name]
    except KeyError:
        raise ValueError("未知产品：%r（已知：%s）"
                         % (name, "、".join(_BY_NAME))) from None


def product_for(subject: Subject) -> Product:
    return _BY_SUBJECT[subject]


def products_for_grade(grade: Grade) -> tuple[Product, ...]:
    """这个年级能开哪些产品 —— 硬约束，S7 不该出现物理化学。"""
    return tuple(p for p in CATALOG if p.available_to(grade))


class Tier(Enum):
    """团队类型 = 能力分层。排在一起的课，层级必须一致 ——
    不能把励学班和乐学班的学生混着连堂。"""
    LI = "LI"
    LE = "LE"
    BO = "BO"
    CX = "CX"
    ZY = "ZY"

    @property
    def label(self) -> str:
        return {"LI": "励学", "LE": "乐学", "BO": "博学",
                "CX": "创新", "ZY": "卓越"}[self.value]
