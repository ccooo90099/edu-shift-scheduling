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


def adjacency_waits(slot_texts):
    """所有"中间夹不下别的课"的相接组合，学生各要等多久（去重排序）。"""
    parsed = sorted(parse_slot(s) for s in slot_texts)
    gap_count = make_gap_counter(slot_texts)
    waits = set()
    for i, a in enumerate(parsed):
        for b in parsed[i + 1:]:
            if b[0] < a[1]:                 # 两个时段重叠，不是先后关系
                continue
            if gap_count(a, b) == 0:
                waits.add(b[0] - a[1])
    return sorted(waits)


def derive_adjacency_limit(slot_texts):
    """从时段表推算"挨着"的间隔上限。

    把相接组合的间隔排序，找最大的一次跳变：跳变以下是课间，以上是午休那种
    真正的休息。教培不是托管，午休家长要把孩子接走，所以跨午休不算"挨着"。

    返回 (上限分钟, 所有间隔, 一句话说明)。推不出来时上限是 None。
    """
    waits = [w for w in adjacency_waits(slot_texts) if w > 0]
    if len(waits) < 2:
        return (waits[0] if waits else None), waits, "时段太少，推不出跳变"

    ratios = [(waits[i + 1] / waits[i], i) for i in range(len(waits) - 1)]
    ratio, index = max(ratios)
    limit = waits[index]
    return limit, waits, ("%d → %d 分钟是最大跳变（%.1f 倍）：%s 算课间，%s 算休息"
                          % (limit, waits[index + 1], ratio,
                             "/".join(str(w) for w in waits if w <= limit),
                             "/".join(str(w) for w in waits if w > limit)))
