"""真实重叠的总容量，以及空教室标签的历史并发回退。"""
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.inputs import Instructor, Team, derive_rooms
from engine.solver import solve


def schedule(slots, labels=None):
    data = {"中心": ["甲"] * len(slots), "段次": ["段1"] * len(slots),
            "周": ["周六"] * len(slots), "首次服务时间": slots}
    if labels is not None:
        data["指导室"] = labels
    return pd.DataFrame(data)


@pytest.mark.parametrize("blank", [None, float("nan"), pd.NA, "", "  "])
def test_missing_room_labels_use_historical_peak(blank):
    df = schedule(["08:10-10:10"] * 2, [blank, blank])
    original = df.copy(deep=True)
    assert derive_rooms(df) == {"甲": 2}
    pd.testing.assert_frame_equal(df, original)


@pytest.mark.parametrize("labels", [None, [None, None]])
def test_historical_peak_includes_overlapping_slot_labels(labels):
    df = schedule(["13:30-15:30", "14:00-16:00"], labels)
    assert derive_rooms(df) == {"甲": 2}


def test_historical_peak_does_not_add_touching_slots_or_other_days():
    df = schedule(["08:00-10:00", "10:00-12:00", "08:00-10:00"])
    df.loc[2, "周"] = "周日"
    assert derive_rooms(df) == {"甲": 1}


def test_historical_peak_uses_largest_day():
    df = schedule(["08:00-10:00"] * 3)
    df.loc[1:, "周"] = "周日"
    assert derive_rooms(df) == {"甲": 2}


def test_valid_room_labels_still_take_priority_and_are_normalized():
    df = schedule(["08:00-10:00"] * 4, ["01", " 01 ", "02", "02"])
    assert derive_rooms(df) == {"甲": 2}


@pytest.mark.parametrize("blank", [None, float("nan"), pd.NA, "", "  "])
def test_partial_room_labels_do_not_underestimate_historical_peak(blank):
    df = schedule(["08:00-10:00"] * 2, [blank, "02"])
    assert derive_rooms(df) == {"甲": 2}


def test_partial_labels_preserve_more_observed_rooms_than_peak():
    df = schedule(["08:00-09:00", "09:00-10:00", "10:00-11:00", "11:00-12:00"],
                  ["01", "02", "03", None])
    assert derive_rooms(df) == {"甲": 3}


def test_room_labels_with_duplicate_dataframe_indices():
    df = schedule(["08:00-10:00"] * 3, ["01", " 01 ", "02"])
    df.index = [0, 0, 1]
    assert derive_rooms(df) == {"甲": 2}


def fixed_slot_resources(slots):
    teams = [Team(str(i), "段1", "周六", "区域", "甲", "甲", "S7", "数学", "LE")
             for i in range(len(slots))]
    teachers = {
        str(i): Instructor(str(i), {"数学"}, {"甲"}, set(slots) - {slot})
        for i, slot in enumerate(slots)
    }
    cfg = {"时段": slots, "连堂": {"规则": []}, "地理": {}, "权重": {}}
    return teams, teachers, cfg


@pytest.mark.parametrize("slots,rooms,unassigned", [
    (["13:30-15:30", "14:00-16:00"], 1, 1),
    (["09:00-12:00", "10:00-13:00", "11:00-14:00"], 2, 1),
    (["08:00-10:00", "10:00-12:00"], 1, 0),
    (["08:00-12:00", "08:00-10:00", "10:00-12:00"], 2, 0),
    (["08:00-10:00"], 0, 1),
])
def test_solver_room_capacity_uses_actual_overlap(slots, rooms, unassigned):
    teams, teachers, cfg = fixed_slot_resources(slots)
    result = solve(teams, teachers, {"甲": rooms}, cfg, time_limit=5, workers=1)
    assert len(result.未排上) == unassigned
