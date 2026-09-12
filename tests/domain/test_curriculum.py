"""产品 ↔ 科目 ↔ 年级。"""
import pytest

from scheduling.domain.model.curriculum import (
    CATALOG, Grade, Subject, Tier, product_of, products_for_grade)


def test_五个产品对应五个科目():
    assert {p.subject for p in CATALOG} == {
        Subject.数学, Subject.英语, Subject.语文, Subject.物理, Subject.化学}
    assert product_of("编程理论").subject is Subject.数学
    assert product_of("溯源").subject is Subject.化学


def test_年级决定能开哪些科():
    assert len(products_for_grade(Grade.S7)) == 3     # 语数英
    assert len(products_for_grade(Grade.S8)) == 4     # 加物理
    assert len(products_for_grade(Grade.S9)) == 5     # 加化学


def test_S7不能开物理化学():
    assert not product_of("躬行实践").available_to(Grade.S7)
    assert not product_of("溯源").available_to(Grade.S8)
    assert product_of("溯源").available_to(Grade.S9)


def test_未知产品报错而不是静默返回None():
    with pytest.raises(ValueError, match="未知产品"):
        product_of("不存在的产品")


def test_层级代码与中文名对得上():
    assert Tier.LI.label == "励学"
    assert Tier.LE.label == "乐学"
