"""仓储接口 —— 依赖倒置的边界。

领域层**定义**这些接口，基础设施层**实现**它们。所以领域层不知道
数据存在 SQLite、xlsx 还是内存里，换掉存储不用改一行业务代码。

用 Protocol 而不是 ABC：不强制继承，测试里随手写个假实现就能用。
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from .model.academic_calendar import AcademicCalendar
from .model.cohort import Cohort, CohortKey
from .model.instructor import Instructor
from .model.venue import Center


@runtime_checkable
class CenterRepository(Protocol):
    def all(self) -> list[Center]: ...
    def get(self, name: str) -> Center | None: ...
    def save(self, center: Center) -> None: ...
    def without_coordinate(self) -> list[Center]:
        """缺坐标的中心 —— 顶部告警条要用。

        缺坐标不会报错，只会让转场判定悄悄退化成三档粗判。
        这种沉默降级必须在界面上一直喊。
        """
        ...


@runtime_checkable
class InstructorRepository(Protocol):
    def all(self) -> list[Instructor]: ...
    def get(self, name: str) -> Instructor | None: ...
    def save(self, instructor: Instructor) -> None: ...
    def save_many(self, instructors) -> None:
        """批量改 —— 整个校区统一加一条不可用时段这类操作。"""
        ...
    def unconfigured(self) -> list[Instructor]:
        """缺资质配置的 —— 同样要进告警条。"""
        ...


@runtime_checkable
class CalendarRepository(Protocol):
    def load(self) -> AcademicCalendar: ...
    def save(self, calendar: AcademicCalendar) -> None: ...


@runtime_checkable
class CohortRepository(Protocol):
    def all(self) -> list[Cohort]: ...
    def get(self, key: CohortKey) -> Cohort | None: ...
    def save(self, cohort: Cohort) -> None: ...


@runtime_checkable
class TaskRepository(Protocol):
    """求解任务。求解要跑很久（不限候选池下 140 秒仍未收敛），
    必须后台异步 + 轮询进度。"""
    def create(self, task) -> str: ...
    def get(self, task_id: str): ...
    def list(self, limit: int = 50) -> list: ...
    def update(self, task) -> None: ...
