"""SQLite 仓储 —— 往返一致性与告警查询。"""
from datetime import date

import pytest

from scheduling.application.dto import SolveTask, TaskStatus
from scheduling.domain.model.academic_calendar import AcademicCalendar, Batch
from scheduling.domain.model.curriculum import product_of
from scheduling.domain.model.instructor import Instructor
from scheduling.domain.model.period import Period, Season
from scheduling.domain.model.timeslot import TimeSlot
from scheduling.domain.model.venue import Center, Coordinate, Datum, Room
from scheduling.domain.repository import (
    CalendarRepository, CenterRepository, InstructorRepository, TaskRepository)
from scheduling.infrastructure.persistence.sqlite import (
    SqliteCalendarRepository, SqliteCenterRepository,
    SqliteInstructorRepository, SqliteTaskRepository, connect)


@pytest.fixture
def conn():
    c = connect(":memory:")
    yield c
    c.close()


def test_四个仓储都满足领域定义的接口(conn):
    """依赖倒置的边界 —— 换实现不该动领域层。"""
    assert isinstance(SqliteCenterRepository(conn), CenterRepository)
    assert isinstance(SqliteInstructorRepository(conn), InstructorRepository)
    assert isinstance(SqliteCalendarRepository(conn), CalendarRepository)
    assert isinstance(SqliteTaskRepository(conn), TaskRepository)


def test_中心往返_坐标系必须原样保留(conn):
    """datum 丢了就等于坐标错了，而且不会报错。"""
    repo = SqliteCenterRepository(conn)
    repo.save(Center("百花科学", "百花", "福田", "红荔西路",
                     Coordinate(114.0579, 22.5431, Datum.BD09),
                     located_by="城市+校区名",
                     rooms=[Room("百花科学", "01", 24),
                            Room("百花科学", "02", 30,
                                 frozenset({TimeSlot.parse("08:10-10:10")}))]))
    got = repo.get("百花科学")
    assert got.coordinate.datum is Datum.BD09
    assert got.coordinate.longitude == 114.0579
    assert got.room_count == 2
    assert got.rooms[1].seats == 30
    assert TimeSlot.parse("08:10-10:10") in got.rooms[1].unavailable


def test_缺坐标的中心能被查出来供告警条用(conn):
    repo = SqliteCenterRepository(conn)
    repo.save(Center("有坐标", "有坐标", coordinate=Coordinate(114.0, 22.5, Datum.WGS84)))
    repo.save(Center("没坐标", "没坐标"))
    assert [c.name for c in repo.without_coordinate()] == ["没坐标"]


def test_教室为估计值的标记会持久化(conn):
    """不能让「估计」在存一遍之后变成「实测」。"""
    repo = SqliteCenterRepository(conn)
    repo.save(Center("甲", "甲", rooms=[Room("甲", "估1")], rooms_are_estimated=True))
    assert repo.get("甲").rooms_are_estimated


def test_指导员批量保存与缺配置查询(conn):
    repo = SqliteInstructorRepository(conn)
    repo.save_many([
        Instructor("甲", {product_of("编程理论")},
                   unavailable_slots={TimeSlot.parse("18:30-20:30")}),
        Instructor("乙"),
    ])
    assert {i.name for i in repo.all()} == {"甲", "乙"}
    assert [i.name for i in repo.unconfigured()] == ["乙"]
    甲 = repo.get("甲")
    assert product_of("编程理论") in 甲.teachable
    assert TimeSlot.parse("18:30-20:30") in 甲.unavailable_slots


def test_日历往返_期位的授课日要保住(conn):
    repo = SqliteCalendarRepository(conn)
    repo.save(AcademicCalendar([
        Batch("暑假一期", Season.寒暑假, date(2024, 7, 6), date(2024, 7, 16),
              {Period.A: [date(2024, 7, 6), date(2024, 7, 7)]})]))
    cal = repo.load()
    assert len(cal) == 1
    b = list(cal)[0]
    assert b.season is Season.寒暑假
    assert b.dates_of(Period.A) == (date(2024, 7, 6), date(2024, 7, 7))


def test_任务往返_求解状态与任务状态是两回事(conn):
    repo = SqliteTaskRepository(conn)
    t = SolveTask(id="t1", name="段次3", season="寒暑假",
                  status=TaskStatus.DONE, solver_status="FEASIBLE",
                  objective=38566.0, best_bound=31232.0,
                  score_breakdown={"转场一次": 20}, unplaced=0,
                  notes=["有解，但未证明最优"])
    repo.create(t)
    got = repo.get("t1")
    assert got.status is TaskStatus.DONE, "任务跑完了"
    assert got.solver_status == "FEASIBLE", "但解没证明最优 —— 两者不能混"
    assert "未证明最优" in got.gap_hint
    assert got.score_breakdown["转场一次"] == 20


def test_任务列表按创建时间倒序(conn):
    repo = SqliteTaskRepository(conn)
    for i in range(3):
        repo.create(SolveTask(id="t%d" % i, name="第%d次" % i, season="寒暑假"))
    assert len(repo.list()) == 3
