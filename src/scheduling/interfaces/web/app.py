"""FastAPI 应用。

**内网部署，不做认证** —— 用户定案：谁能访问谁能用。
所以这里没有登录、没有权限，也不该有。

页面用 Jinja2 + HTMX 渲染，不是 SPA：排班是「表单 → 等待 → 看结果」的流程，
引入 Node 工具链只会给内网部署多加一层构建依赖。
"""
from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ...application.dto import SolveTask, TaskStatus
from ...domain.model.curriculum import product_of
from ...domain.model.instructor import Instructor
from ...domain.model.timeslot import TimeSlot
from ...domain.model.venue import Center, Coordinate, MAP_SOURCE_DATUM, Room
from .container import Container

HERE = Path(__file__).parent
templates = Jinja2Templates(directory=str(HERE / "templates"))

#: 求解跑很久（大候选池下可能几分钟不收敛），必须后台跑 + 轮询。
#: 内网并发个位数，线程池就够，不引入 Celery/Redis。
_pool = ThreadPoolExecutor(max_workers=2)


def create_app(container: Container | None = None) -> FastAPI:
    app = FastAPI(title="排班系统", docs_url="/api/docs")
    app.state.container = container or Container.build()
    static = HERE / "static"
    static.mkdir(exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static)), name="static")

    def get_container(request: Request) -> Container:
        return request.app.state.container

    def render(request: Request, template: str, **ctx) -> HTMLResponse:
        """所有页面共用的渲染入口 —— 顺手把告警条数据带上，
        免得某个页面忘了传就悄悄不显示了。"""
        c = get_container(request)
        ctx.setdefault("readiness", c.check_readiness())
        return templates.TemplateResponse(request, template, ctx)

    # ------------------------------------------------------------ 首页

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request, c: Container = Depends(get_container)):
        return render(request, "index.html", tasks=c.tasks.list(20))

    # ------------------------------------------------------------ 中心

    @app.get("/centers", response_class=HTMLResponse)
    def centers_page(request: Request, filter: str = "",
                     c: Container = Depends(get_container)):
        items = c.centers.all()
        if filter == "missing-coordinate":
            items = [x for x in items if not x.has_coordinate]
        elif filter == "estimated-rooms":
            items = [x for x in items if x.rooms_are_estimated]
        return render(request, "centers.html", centers=items, filter=filter,
                      map_sources=list(MAP_SOURCE_DATUM))

    @app.post("/centers")
    def save_center(name: str = Form(...), campus: str = Form(""),
                    region: str = Form(""), address: str = Form(""),
                    rooms: int = Form(0),
                    c: Container = Depends(get_container)):
        existing = c.centers.get(name)
        center = existing or Center(name=name, campus=campus or Center.campus_of(name))
        center.campus = campus or Center.campus_of(name)
        center.region, center.address = region, address
        if rooms and not center.rooms:
            center.rooms = [Room(name, "R%d" % i) for i in range(1, rooms + 1)]
            center.rooms_are_estimated = True
        c.centers.save(center)
        return RedirectResponse("/centers", status_code=303)

    @app.post("/centers/{name}/coordinate")
    def set_coordinate(name: str, longitude: float = Form(...),
                       latitude: float = Form(...), map_source: str = Form(...),
                       c: Container = Depends(get_container)):
        """手动补录坐标。

        让用户选**地图来源**（他知道），系统据此定坐标系（他不该需要知道）。
        来源不认识就报错 —— 猜错会让距离静默偏差几百米。
        """
        center = c.centers.get(name)
        if center is None:
            raise HTTPException(404, "没有这个中心：%s" % name)
        try:
            center.coordinate = Coordinate.from_map_source(
                longitude, latitude, map_source)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        center.located_by = "手动补录（%s）" % map_source
        c.centers.save(center)
        return RedirectResponse("/centers", status_code=303)

    # ------------------------------------------------------------ 指导员

    @app.get("/instructors", response_class=HTMLResponse)
    def instructors_page(request: Request, filter: str = "",
                         c: Container = Depends(get_container)):
        items = c.instructors.all()
        if filter == "unconfigured":
            items = [x for x in items if not x.is_configured]
        return render(request, "instructors.html", instructors=items,
                      filter=filter, centers=c.centers.all())

    @app.post("/instructors")
    def save_instructor(name: str = Form(...), products: str = Form(""),
                        centers: str = Form(""), unavailable: str = Form(""),
                        max_sessions: int = Form(4),
                        c: Container = Depends(get_container)):
        def parse(text):
            return [x.strip() for x in text.replace("，", ",").split(",") if x.strip()]
        try:
            teachable = {product_of(p) for p in parse(products)}
            slots = {TimeSlot.parse(s) for s in parse(unavailable)}
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        c.instructors.save(Instructor(
            name=name, teachable=teachable, allowed_centers=set(parse(centers)),
            unavailable_slots=slots, max_sessions_per_day=max_sessions))
        return RedirectResponse("/instructors", status_code=303)

    @app.post("/instructors/bulk")
    def bulk_edit(names: str = Form(...), products: str = Form(""),
                  max_sessions: int = Form(0),
                  c: Container = Depends(get_container)):
        """批量改 —— 整批新老师统一设可教产品这类操作。"""
        def parse(text):
            return [x.strip() for x in text.replace("，", ",").split(",") if x.strip()]
        targets = []
        for n in parse(names):
            inst = c.instructors.get(n) or Instructor(name=n)
            if products:
                inst.teachable = {product_of(p) for p in parse(products)}
            if max_sessions:
                inst.max_sessions_per_day = max_sessions
            targets.append(inst)
        if targets:
            c.instructors.save_many(targets)
        return RedirectResponse("/instructors", status_code=303)

    # ------------------------------------------------------------ 任务

    @app.get("/tasks/{task_id}", response_class=HTMLResponse)
    def task_page(request: Request, task_id: str,
                  c: Container = Depends(get_container)):
        task = c.tasks.get(task_id)
        if task is None:
            raise HTTPException(404, "没有这个任务")
        return render(request, "task.html", task=task)

    @app.get("/tasks/{task_id}/progress", response_class=HTMLResponse)
    def task_progress(request: Request, task_id: str,
                      c: Container = Depends(get_container)):
        """HTMX 轮询这个片段。任务终结后返回的片段不再带轮询属性，
        前端自然停下来，不需要额外的停止逻辑。"""
        task = c.tasks.get(task_id)
        if task is None:
            raise HTTPException(404, "没有这个任务")
        return templates.TemplateResponse(
            request, "_progress.html", {"task": task})

    @app.post("/tasks")
    async def create_task(name: str = Form(...), season: str = Form("寒暑假"),
                          upload: UploadFile | None = None,
                          c: Container = Depends(get_container)):
        task = SolveTask(id=uuid.uuid4().hex[:12], name=name, season=season)
        if upload is not None and upload.filename:
            dest = c.data_dir / "uploads" / ("%s-%s" % (task.id, upload.filename))
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(await upload.read())
            task.input_path = str(dest)
        c.tasks.create(task)
        return RedirectResponse("/tasks/%s" % task.id, status_code=303)

    @app.get("/tasks/{task_id}/download")
    def download(task_id: str, c: Container = Depends(get_container)):
        task = c.tasks.get(task_id)
        if task is None or not task.output_path:
            raise HTTPException(404, "还没有产物")
        return FileResponse(task.output_path, filename=Path(task.output_path).name)

    # ------------------------------------------------------------ 健康检查

    @app.get("/api/readiness")
    def api_readiness(c: Container = Depends(get_container)):
        return [vars(v) for v in c.check_readiness()]

    @app.get("/api/tasks/{task_id}")
    def api_task(task_id: str, c: Container = Depends(get_container)):
        task = c.tasks.get(task_id)
        if task is None:
            raise HTTPException(404, "没有这个任务")
        return {
            "id": task.id, "name": task.name,
            "status": task.status.value, "status_label": task.status.label,
            "solver_status": task.solver_status,
            "objective": task.objective, "best_bound": task.best_bound,
            "gap_hint": task.gap_hint, "unplaced": task.unplaced,
            "elapsed_seconds": round(task.elapsed_seconds, 1),
            "score_breakdown": task.score_breakdown, "notes": task.notes,
        }

    return app


app = create_app
