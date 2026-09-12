"""SQLite 仓储实现。

单机内网，并发个位数，所以省掉一个数据库容器。

长期主数据（中心、教室、指导员、日历）建成正式字段而不是 JSON ——
它们要支持列表页、批量编辑和「缺配置」查询（顶部告警条要用）。
求解任务的配置存 JSON：规则字段还在演进，建成表结构会天天改 schema。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path

from ...application.dto import SolveTask, TaskStatus
from ...domain.model.academic_calendar import AcademicCalendar, Batch
from ...domain.model.curriculum import Grade, Tier, product_of
from ...domain.model.instructor import Instructor
from ...domain.model.period import Period, Season
from ...domain.model.timeslot import TimeSlot
from ...domain.model.venue import Center, Coordinate, Datum, Room

SCHEMA = """
CREATE TABLE IF NOT EXISTS center (
    name        TEXT PRIMARY KEY,
    campus      TEXT NOT NULL,
    region      TEXT NOT NULL DEFAULT '',
    address     TEXT NOT NULL DEFAULT '',
    longitude   REAL,
    latitude    REAL,
    datum       TEXT,
    located_by  TEXT NOT NULL DEFAULT '',
    rooms_estimated INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS room (
    center      TEXT NOT NULL REFERENCES center(name) ON DELETE CASCADE,
    room_id     TEXT NOT NULL,
    seats       INTEGER NOT NULL DEFAULT 0,
    unavailable TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (center, room_id)
);
CREATE TABLE IF NOT EXISTS instructor (
    name            TEXT PRIMARY KEY,
    teachable       TEXT NOT NULL DEFAULT '[]',
    allowed_centers TEXT NOT NULL DEFAULT '[]',
    unavailable_slots TEXT NOT NULL DEFAULT '[]',
    unavailable_weekdays TEXT NOT NULL DEFAULT '[]',
    max_sessions    INTEGER NOT NULL DEFAULT 4,
    max_centers     INTEGER NOT NULL DEFAULT 2,
    immutable       INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS batch (
    name        TEXT PRIMARY KEY,
    season      TEXT NOT NULL,
    start_date  TEXT NOT NULL,
    end_date    TEXT NOT NULL,
    period_dates TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS task (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    season      TEXT NOT NULL,
    status      TEXT NOT NULL,
    config      TEXT NOT NULL DEFAULT '{}',
    input_path  TEXT NOT NULL DEFAULT '',
    output_path TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    started_at  TEXT,
    finished_at TEXT,
    solver_status TEXT NOT NULL DEFAULT '',
    objective   REAL,
    best_bound  REAL,
    score_breakdown TEXT NOT NULL DEFAULT '{}',
    unplaced    INTEGER NOT NULL DEFAULT 0,
    notes       TEXT NOT NULL DEFAULT '[]',
    error       TEXT NOT NULL DEFAULT ''
);
"""


def connect(path) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def _dt(value):
    return datetime.fromisoformat(value) if value else None


class SqliteCenterRepository:
    def __init__(self, conn):
        self._c = conn

    def _rooms(self, name):
        rows = self._c.execute(
            "SELECT * FROM room WHERE center = ? ORDER BY room_id", (name,))
        return [Room(name, r["room_id"], r["seats"],
                     frozenset(TimeSlot.parse(t) for t in json.loads(r["unavailable"])))
                for r in rows]

    def _build(self, row) -> Center:
        coord = None
        if row["longitude"] is not None and row["datum"]:
            coord = Coordinate(row["longitude"], row["latitude"], Datum(row["datum"]))
        return Center(name=row["name"], campus=row["campus"], region=row["region"],
                      address=row["address"], coordinate=coord,
                      located_by=row["located_by"], rooms=self._rooms(row["name"]),
                      rooms_are_estimated=bool(row["rooms_estimated"]))

    def all(self):
        return [self._build(r) for r in
                self._c.execute("SELECT * FROM center ORDER BY name")]

    def get(self, name):
        row = self._c.execute("SELECT * FROM center WHERE name = ?", (name,)).fetchone()
        return self._build(row) if row else None

    def save(self, center: Center):
        c = center.coordinate
        self._c.execute(
            "INSERT INTO center (name, campus, region, address, longitude, latitude,"
            " datum, located_by, rooms_estimated) VALUES (?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(name) DO UPDATE SET campus=excluded.campus,"
            " region=excluded.region, address=excluded.address,"
            " longitude=excluded.longitude, latitude=excluded.latitude,"
            " datum=excluded.datum, located_by=excluded.located_by,"
            " rooms_estimated=excluded.rooms_estimated",
            (center.name, center.campus, center.region, center.address,
             c.longitude if c else None, c.latitude if c else None,
             c.datum.value if c else None, center.located_by,
             int(center.rooms_are_estimated)))
        self._c.execute("DELETE FROM room WHERE center = ?", (center.name,))
        self._c.executemany(
            "INSERT INTO room (center, room_id, seats, unavailable) VALUES (?,?,?,?)",
            [(center.name, r.room_id, r.seats,
              json.dumps([s.text for s in sorted(r.unavailable)]))
             for r in center.rooms])
        self._c.commit()

    def without_coordinate(self):
        return [self._build(r) for r in self._c.execute(
            "SELECT * FROM center WHERE longitude IS NULL OR datum IS NULL"
            " ORDER BY name")]


class SqliteInstructorRepository:
    def __init__(self, conn):
        self._c = conn

    @staticmethod
    def _build(row) -> Instructor:
        return Instructor(
            name=row["name"],
            teachable={product_of(p) for p in json.loads(row["teachable"])},
            allowed_centers=set(json.loads(row["allowed_centers"])),
            unavailable_slots={TimeSlot.parse(t)
                               for t in json.loads(row["unavailable_slots"])},
            unavailable_weekdays=set(json.loads(row["unavailable_weekdays"])),
            max_sessions_per_day=row["max_sessions"],
            max_centers_per_day=row["max_centers"],
            is_immutable=bool(row["immutable"]))

    def all(self):
        return [self._build(r) for r in
                self._c.execute("SELECT * FROM instructor ORDER BY name")]

    def get(self, name):
        row = self._c.execute(
            "SELECT * FROM instructor WHERE name = ?", (name,)).fetchone()
        return self._build(row) if row else None

    def save(self, i: Instructor):
        self.save_many([i])

    def save_many(self, instructors):
        """批量改 —— 整个校区统一加一条不可用时段这类操作。"""
        self._c.executemany(
            "INSERT INTO instructor (name, teachable, allowed_centers,"
            " unavailable_slots, unavailable_weekdays, max_sessions,"
            " max_centers, immutable) VALUES (?,?,?,?,?,?,?,?)"
            " ON CONFLICT(name) DO UPDATE SET teachable=excluded.teachable,"
            " allowed_centers=excluded.allowed_centers,"
            " unavailable_slots=excluded.unavailable_slots,"
            " unavailable_weekdays=excluded.unavailable_weekdays,"
            " max_sessions=excluded.max_sessions,"
            " max_centers=excluded.max_centers, immutable=excluded.immutable",
            [(i.name, json.dumps(sorted(p.name for p in i.teachable),
                                 ensure_ascii=False),
              json.dumps(sorted(i.allowed_centers), ensure_ascii=False),
              json.dumps(sorted(s.text for s in i.unavailable_slots)),
              json.dumps(sorted(i.unavailable_weekdays), ensure_ascii=False),
              i.max_sessions_per_day, i.max_centers_per_day, int(i.is_immutable))
             for i in instructors])
        self._c.commit()

    def unconfigured(self):
        return [self._build(r) for r in self._c.execute(
            "SELECT * FROM instructor WHERE teachable IN ('[]', '') ORDER BY name")]


class SqliteCalendarRepository:
    def __init__(self, conn):
        self._c = conn

    def load(self) -> AcademicCalendar:
        batches = []
        for r in self._c.execute("SELECT * FROM batch ORDER BY start_date"):
            raw = json.loads(r["period_dates"])
            batches.append(Batch(
                name=r["name"], season=Season(r["season"]),
                start=date.fromisoformat(r["start_date"]),
                end=date.fromisoformat(r["end_date"]),
                period_dates={Period(k): [date.fromisoformat(d) for d in v]
                              for k, v in raw.items()}))
        return AcademicCalendar(batches)

    def save(self, calendar: AcademicCalendar):
        self._c.execute("DELETE FROM batch")
        self._c.executemany(
            "INSERT INTO batch (name, season, start_date, end_date, period_dates)"
            " VALUES (?,?,?,?,?)",
            [(b.name, b.season.value, b.start.isoformat(), b.end.isoformat(),
              json.dumps({p.value: [d.isoformat() for d in ds]
                          for p, ds in b.period_dates.items()}))
             for b in calendar])
        self._c.commit()


class SqliteTaskRepository:
    def __init__(self, conn):
        self._c = conn

    @staticmethod
    def _build(row) -> SolveTask:
        return SolveTask(
            id=row["id"], name=row["name"], season=row["season"],
            status=TaskStatus(row["status"]), config=json.loads(row["config"]),
            input_path=row["input_path"], output_path=row["output_path"],
            created_at=_dt(row["created_at"]), started_at=_dt(row["started_at"]),
            finished_at=_dt(row["finished_at"]),
            solver_status=row["solver_status"], objective=row["objective"],
            best_bound=row["best_bound"],
            score_breakdown=json.loads(row["score_breakdown"]),
            unplaced=row["unplaced"], notes=json.loads(row["notes"]),
            error=row["error"])

    def create(self, task: SolveTask) -> str:
        self.update(task)
        return task.id

    def get(self, task_id):
        row = self._c.execute("SELECT * FROM task WHERE id = ?", (task_id,)).fetchone()
        return self._build(row) if row else None

    def list(self, limit: int = 50):
        return [self._build(r) for r in self._c.execute(
            "SELECT * FROM task ORDER BY created_at DESC LIMIT ?", (limit,))]

    def update(self, t: SolveTask):
        self._c.execute(
            "INSERT INTO task (id, name, season, status, config, input_path,"
            " output_path, created_at, started_at, finished_at, solver_status,"
            " objective, best_bound, score_breakdown, unplaced, notes, error)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(id) DO UPDATE SET name=excluded.name,"
            " status=excluded.status, config=excluded.config,"
            " input_path=excluded.input_path, output_path=excluded.output_path,"
            " started_at=excluded.started_at, finished_at=excluded.finished_at,"
            " solver_status=excluded.solver_status, objective=excluded.objective,"
            " best_bound=excluded.best_bound,"
            " score_breakdown=excluded.score_breakdown,"
            " unplaced=excluded.unplaced, notes=excluded.notes, error=excluded.error",
            (t.id, t.name, t.season, t.status.value,
             json.dumps(t.config, ensure_ascii=False), t.input_path, t.output_path,
             t.created_at.isoformat(),
             t.started_at.isoformat() if t.started_at else None,
             t.finished_at.isoformat() if t.finished_at else None,
             t.solver_status, t.objective, t.best_bound,
             json.dumps(t.score_breakdown, ensure_ascii=False), t.unplaced,
             json.dumps(t.notes, ensure_ascii=False), t.error))
        self._c.commit()
