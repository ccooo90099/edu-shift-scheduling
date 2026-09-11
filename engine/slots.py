"""时段的钟点运算 —— "挨着"和"赶得及"都靠它。

本项目的时段空隙极不均匀（20/90/20/10 分钟），所以一切判断按真实钟点走，
不按格子序号。
"""


def to_min(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def parse_slot(text):
    """'08:10-10:10' → (490, 610)"""
    a, b = text.split("-")
    return to_min(a), to_min(b)


def overlaps(a, b):
    """两个时段是否在时间上重叠——重叠就意味着学生/老师分身。"""
    return a[0] < b[1] and b[0] < a[1]


def make_gap_counter(slot_texts):
    """返回 gap_count(a, b)：a 结束到 b 开始之间，还塞得下几个别的时段。

    0 表示两节课首尾相接（中间没有别的课），这才叫"挨着"。
    """
    parsed = sorted(parse_slot(s) for s in slot_texts)

    def gap_count(a, b):
        return sum(1 for s in parsed if a[1] <= s[0] and s[1] <= b[0])

    return gap_count
