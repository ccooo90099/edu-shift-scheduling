"""排班结果的机器可读副本。

xlsx 是给人看和给人下载的；网页要按日期展开课表、按校区筛选，
再去解析 xlsx 里的中文标签（「第一期」还是「周六」）就太脆了 ——
期位是个枚举，落盘时就该保持枚举形态。

所以产物写两份：`<id>.xlsx` 给人，`<id>.json` 给程序。
两份出自**同一次求解结果**，不会对不上。
"""
from __future__ import annotations

import json
from pathlib import Path


def dump(path, teams, season, outcome=None) -> Path:
    payload = {
        "season": season.value,
        "solver_status": getattr(outcome, "status", ""),
        "teams": [{
            "id": t.id,
            "name": t.name,
            "center": t.center,
            "campus": t.campus,
            "region": t.region,
            "grade": t.grade.value,
            "product": t.product.name,
            "subject": t.product.subject.value,
            "tier": t.tier.value,
            "headcount": t.headcount,
            "is_promotional": t.is_promotional,
            "period": t.period.value if t.period else None,
            "slot": t.slot.text if t.slot else None,
            "slot_start": t.slot.start if t.slot else None,
            "instructor": t.instructor,
            "room": t.room,
            "placed": t.is_scheduled,
        } for t in teams],
    }
    p = Path(path)
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return p


def load(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))
