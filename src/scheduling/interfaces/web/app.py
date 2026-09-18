"""FastAPI 应用。

**内网部署，不做认证** —— 用户定案：谁能访问谁能用。
所以这里没有登录、没有权限，也不该有。

页面用 Jinja2 + HTMX 渲染，不是 SPA：排班是「表单 → 等待 → 看结果」的流程，
引入 Node 工具链只会给内网部署多加一层构建依赖。
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import date, datetime
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import (
    FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ...application.dto import SolveTask, TaskStatus
from ...domain.model.curriculum import product_of
from ...domain.model.instructor import Instructor
from ...domain.model.timeslot import TimeSlot
from ...domain.model.venue import Center, Coordinate, MAP_SOURCE_DATUM, Room
from ...application.use_cases.build_problem import BuildProblem
from ...application.use_cases.demo_dataset import DemoDataset
from ...application.use_cases.schedule_view import (
    RANGES, ScheduleView, date_range)
from ...infrastructure.spreadsheet import result_json
from ...application.use_cases.seed_demo import SeedDemo
from ...domain.model.academic_calendar import AcademicCalendar, Batch
from ...domain.model.period import Period, Season
from ...domain.policy.travel import normalize_adjacency
from .container import Container
from .gate import COOKIE_NAME, PasswordGate, is_public, safe_next, startup_banner

HERE = Path(__file__).parent
templates = Jinja2Templates(directory=str(HERE / "templates"))

#: 求解跑很久（大候选池下可能几分钟不收敛），必须后台跑 + 轮询。
#: 内网并发个位数，线程池就够，不引入 Celery/Redis。
_pool = ThreadPoolExecutor(max_workers=2)


#: 区域相邻表存成一个 json 文件。它是配置不是主数据，量小、改得少，
#: 不值得为它单开一张表。
def _adjacency_path(c: Container):
    return c.data_dir / "region_adjacency.json"


def _load_adjacency(c: Container) -> dict:
    path = _adjacency_path(c)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_adjacency(c: Container, raw: dict) -> None:
    _adjacency_path(c).write_text(
        json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")


#: 校区并发上限。粒度不固定 —— 有的校区卡在某栋楼的教室数，
#: 有的卡在整个校区能同时开几个班，所以两层都做成配置。
def _caps_path(c: Container):
    return c.data_dir / "campus_caps.json"


def _load_caps(c: Container) -> dict:
    path = _caps_path(c)
    if not path.exists():
        return {}
    try:
        return {k: int(v) for k, v in json.loads(path.read_text(encoding="utf-8")).items()}
    except (json.JSONDecodeError, OSError, ValueError, TypeError):
        return {}


def _save_caps(c: Container, caps: dict) -> None:
    _caps_path(c).write_text(
        json.dumps(caps, ensure_ascii=False, indent=2), encoding="utf-8")


#: 规则配置。真实的 config/rules.yaml 不入库；没有就退回示例。
def _config_path() -> str:
    for name in ("config/rules.yaml", "config/rules.example.yaml"):
        if Path(name).exists():
            return name
    return ""


CONFIG_PATH = _config_path()


#: 解析结果按 (路径, 修改时间) 缓存。
#: 产物一旦写出就不再变，而进度页每 2–3 秒刷一次 —— 每次都重新解析
#: 整个 xlsx 在 Render 免费档那种共享 CPU 上是实打实的卡顿来源。
_BOARD_CACHE: dict[tuple, dict] = {}


def _read_workbook(path) -> dict:
    """一次打开，把看板、明细、没排上的全读出来。

    直接读已经写好的 xlsx，而不是在内存里再拼一次 —— 网页看到的和
    下载下来的必须是同一份东西，两处各算一遍迟早会对不上。

    ⚠️ 之前这里把工作簿开了**三次**（看板一次、判断明细在不在一次、
    读明细一次）。产物不大时看不出来，在慢机器上每次刷新都要等。
    """
    from openpyxl import load_workbook

    key = (str(path), Path(path).stat().st_mtime_ns)
    hit = _BOARD_CACHE.get(key)
    if hit is not None:
        return hit

    wb = load_workbook(path, read_only=True)
    try:
        board = ([[c if c is not None else "" for c in r]
                  for r in wb["看板"].iter_rows(values_only=True)]
                 if "看板" in wb.sheetnames else [])
        detail = ([list(r) for r in wb["排班明细"].iter_rows(values_only=True)]
                  if "排班明细" in wb.sheetnames else [])
    finally:
        wb.close()

    unplaced = []
    if detail:
        head = [str(h or "") for h in detail[0]]
        if "首次服务时间" in head:
            slot_at = head.index("首次服务时间")
            for row in detail[1:]:
                if slot_at < len(row) and not row[slot_at]:
                    unplaced.append({k: (row[i] if i < len(row) else "")
                                     for i, k in enumerate(head)})

    result = {
        "grid": {"head": board[0], "body": board[1:]} if board else None,
        "detail": {"head": detail[0], "body": detail[1:]} if detail else None,
        "unplaced": unplaced,
    }
    _BOARD_CACHE.clear()          # 只留最近一份，别让它无限长
    _BOARD_CACHE[key] = result
    return result


def create_app(container: Container | None = None,
               gate: PasswordGate | None = None) -> FastAPI:
    app = FastAPI(title="排班系统", docs_url=None, redoc_url=None)
    app.state.container = container or Container.build()
    app.state.gate = gate or PasswordGate()
    static = HERE / "static"
    static.mkdir(exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static)), name="static")

    print(startup_banner(app.state.gate), flush=True)

    # 免费 PaaS 大多重启就清空文件系统，SQLite 一起没。每次醒来一个空系统，
    # demo 没法看。灌一份**全是编的**示例数据 —— 真实门店与姓名不进仓库。
    if os.environ.get("SCHEDULING_SEED_DEMO", "").strip() in ("1", "true", "yes"):
        c = app.state.container
        if SeedDemo(c.centers, c.instructors, c.calendars)():
            print("[种子] 库是空的，已灌入示例数据（全部虚构，非真实门店与姓名）",
                  flush=True)

    def get_container(request: Request) -> Container:
        return request.app.state.container

    @app.middleware("http")
    async def require_password(request: Request, call_next):
        """口令门禁。放行的路径见 gate.PUBLIC_PREFIXES。

        API 走 401 + JSON（curl 拿到一坨登录页 HTML 会很莫名），
        页面走 302 到登录页并带上 next，登录完回到原处。
        """
        if is_public(request.url.path) or request.app.state.gate.verify(
                request.cookies.get(COOKIE_NAME)):
            return await call_next(request)
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": "需要口令，先访问 /login"}, status_code=401)
        return RedirectResponse("/login?next=%s" % request.url.path, status_code=303)

    @app.get("/healthz", response_class=PlainTextResponse)
    def healthz():
        """容器探活。**不能拿 /api/readiness 当探活** —— 那个要口令，
        容器会一直被判成不健康。"""
        return "ok"

    @app.get("/login", response_class=HTMLResponse)
    def login_page(request: Request, next: str = "/", error: str = ""):
        return templates.TemplateResponse(
            request, "login.html",
            {"next": next or "/", "error": error, "readiness": []})

    @app.post("/login")
    def do_login(request: Request, password: str = Form(""), next: str = Form("/")):
        if not request.app.state.gate.check_password(password):
            return RedirectResponse(
                "/login?next=%s&error=1" % (next or "/"), status_code=303)
        resp = RedirectResponse(safe_next(next), status_code=303)
        resp.set_cookie(
            COOKIE_NAME, request.app.state.gate.issue(),
            max_age=request.app.state.gate.ttl_seconds,
            httponly=True,        # JS 读不到，少一条泄露途径
            samesite="lax")
        return resp

    @app.post("/logout")
    def do_logout():
        resp = RedirectResponse("/login", status_code=303)
        resp.delete_cookie(COOKIE_NAME)
        return resp

    def render(request: Request, template: str, **ctx) -> HTMLResponse:
        """所有页面共用的渲染入口 —— 顺手把告警条数据带上，
        免得某个页面忘了传就悄悄不显示了。"""
        c = get_container(request)
        ctx.setdefault("readiness", c.check_readiness())
        return templates.TemplateResponse(request, template, ctx)

    # ------------------------------------------------------------ 首页：看排班

    def _latest_result(c: Container):
        """最近一次成功排班的结果。首页看的就是它。"""
        for task in c.tasks.list(30):
            if task.status.value != "done" or not task.output_path:
                continue
            side = Path(task.output_path).with_suffix(".json")
            if side.exists():
                return task, result_json.load(side)
        return None, None

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request, scope: str = "week", on: str = "",
              c: Container = Depends(get_container)):
        """首页只做一件事：看排班。改配置去配置中心。"""
        task, result = _latest_result(c)
        scope = scope if scope in RANGES else "week"
        try:
            anchor = date.fromisoformat(on) if on else None
        except ValueError:
            anchor = None

        view = ScheduleView(c.calendars.load())
        start, end = date_range(scope, anchor)
        days = view.days_in(result, start, end) if result else []
        return render(request, "index.html",
                      task=task, days=days, scope=scope, ranges=RANGES,
                      start=start, end=end, anchor=anchor or date.today(),
                      why_empty=view.why_empty(result),
                      total_lessons=sum(d.count for d in days))

    @app.get("/tasks", response_class=HTMLResponse)
    def task_list(request: Request, c: Container = Depends(get_container)):
        return render(request, "tasks.html", tasks=c.tasks.list(30))

    # ------------------------------------------------------------ 配置中心

    @app.get("/settings", response_class=HTMLResponse)
    def settings(request: Request, c: Container = Depends(get_container)):
        """所有配置的入口。首页不放这些 —— 看结果和改配置是两件事。"""
        centers = c.centers.all()
        instructors = c.instructors.all()
        cal = c.calendars.load()
        caps = _load_caps(c)
        adjacency = normalize_adjacency(_load_adjacency(c))
        regions = sorted({x.region for x in centers if x.region})
        items = [
            {"route": "/centers", "title": "中心与教室",
             "desc": "中心、校区、区域、坐标、每个中心几间教室",
             "stat": "%d 个中心 · %d 间教室" % (
                 len(centers), sum(x.room_count for x in centers)),
             "todo": ("%d 个缺坐标" % sum(1 for x in centers if not x.has_coordinate)
                      if any(not x.has_coordinate for x in centers) else "")},
            {"route": "/instructors", "title": "指导员",
             "desc": "可教产品、可去中心、不可用时段、单日上限",
             "stat": "%d 位" % len(instructors),
             "todo": ("%d 位缺配置" % sum(1 for x in instructors if not x.is_configured)
                      if any(not x.is_configured for x in instructors) else "")},
            {"route": "/capacity", "title": "场地容量",
             "desc": "校区同时最多开几个班（在教室数之外再加一层）",
             "stat": "%d 个校区设了上限" % len(caps),
             "todo": ""},
            {"route": "/regions", "title": "区域相邻",
             "desc": "哪些区之间算「相邻」，决定跨中心的远近档位",
             "stat": "%d / %d 个区配了" % (
                 len([r for r in regions if adjacency.get(r)]), len(regions)),
             "todo": ("%d 个区没配，一律按跨区域算"
                      % len([r for r in regions if not adjacency.get(r)])
                      if any(not adjacency.get(r) for r in regions) else "")},
            {"route": "/calendar", "title": "学年日历",
             "desc": "各批次的起止日期与上课日 —— 首页按天看排班靠它",
             "stat": "%d 个批次" % len(cal),
             "todo": "还没填" if cal.is_empty else ""},
        ]
        return render(request, "settings.html", items=items)

    @app.get("/demo-data", response_class=HTMLResponse)
    def demo_data(request: Request):
        """示例数据长什么样 —— 点「生成」之前先看看。"""
        data = DemoDataset()
        centers = data.centers()
        instructors = data.instructors(centers)
        df = data.teams_frame(centers)
        return render(request, "demo_data.html",
                      centers=centers, instructors=instructors,
                      n_literature=sum(1 for c in centers
                                       if c.name.endswith("文学")),
                      teams=df.to_dict("records"),
                      by_product=df["产品"].value_counts().to_dict(),
                      by_grade=df["程度"].value_counts().to_dict())

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
                    rooms: int = Form(-1),
                    c: Container = Depends(get_container)):
        existing = c.centers.get(name)
        center = existing or Center(name=name, campus=campus or Center.campus_of(name))
        center.campus = campus or Center.campus_of(name)
        center.region, center.address = region, address
        if rooms >= 0:
            # 后台填的是实数，覆盖掉从历史并发推出来的估计值
            center.set_room_count(rooms, estimated=False)
        c.centers.save(center)
        return RedirectResponse("/centers", status_code=303)

    @app.post("/centers/{name}/rooms")
    def set_rooms(name: str, count: int = Form(...),
                  c: Container = Depends(get_container)):
        """单独改教室数。这是**实数**，不是估计 —— 人填的比从历史推的可信。"""
        center = c.centers.get(name)
        if center is None:
            raise HTTPException(404, "没有这个中心：%s" % name)
        try:
            center.set_room_count(count, estimated=False)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
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

    # ------------------------------------------------------------ 学年日历

    @app.get("/calendar", response_class=HTMLResponse)
    def calendar_page(request: Request, c: Container = Depends(get_container)):
        cal = c.calendars.load()
        batches = list(cal)
        return render(request, "calendar.html", batches=batches,
                      seasons=[s.value for s in Season],
                      periods=[(p.value, p) for p in (Period.A, Period.B)],
                      overlaps=cal.overlapping_pairs())

    @app.post("/calendar")
    def save_batch(name: str = Form(...), season: str = Form(...),
                   start: str = Form(...), end: str = Form(...),
                   dates_a: str = Form(""), dates_b: str = Form(""),
                   c: Container = Depends(get_container)):
        def parse_days(text):
            out = []
            for chunk in (text or "").replace("，", ",").replace("\n", ",").split(","):
                chunk = chunk.strip()
                if not chunk:
                    continue
                try:
                    out.append(date.fromisoformat(chunk))
                except ValueError:
                    raise HTTPException(
                        400, "日期要写成 2026-07-06 这种格式，收到 %r" % chunk) from None
            return out

        try:
            batch = Batch(name=name, season=Season(season),
                          start=date.fromisoformat(start),
                          end=date.fromisoformat(end),
                          period_dates={Period.A: parse_days(dates_a),
                                        Period.B: parse_days(dates_b)})
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None

        cal = c.calendars.load()
        kept = [b for b in cal if b.name != name]      # 同名视为覆盖
        c.calendars.save(AcademicCalendar(kept + [batch]))
        return RedirectResponse("/calendar", status_code=303)

    @app.post("/calendar/{name}/delete")
    def delete_batch(name: str, c: Container = Depends(get_container)):
        cal = c.calendars.load()
        c.calendars.save(AcademicCalendar([b for b in cal if b.name != name]))
        return RedirectResponse("/calendar", status_code=303)

    # ------------------------------------------------------------ 场地容量

    @app.get("/capacity", response_class=HTMLResponse)
    def capacity_page(request: Request, c: Container = Depends(get_container)):
        centers = c.centers.all()
        caps = _load_caps(c)
        campuses = sorted({x.campus for x in centers})
        rows = []
        for campus in campuses:
            members = [x for x in centers if x.campus == campus]
            rows.append({
                "campus": campus,
                "centers": members,
                "room_total": sum(x.room_count for x in members),
                "cap": caps.get(campus),
                "estimated": any(x.rooms_are_estimated for x in members)})
        return render(request, "capacity.html", rows=rows)

    @app.post("/capacity")
    def save_cap(campus: str = Form(...), cap: str = Form(""),
                 c: Container = Depends(get_container)):
        """设/清校区并发上限。留空 = 不设这一层，只按各中心的教室数限制。"""
        caps = _load_caps(c)
        text = (cap or "").strip()
        if not text:
            caps.pop(campus, None)
        else:
            try:
                value = int(text)
            except ValueError:
                raise HTTPException(400, "校区上限要填整数，收到 %r" % cap) from None
            if value < 0:
                raise HTTPException(400, "校区上限不能为负")
            caps[campus] = value
        _save_caps(c, caps)
        return RedirectResponse("/capacity", status_code=303)

    # ------------------------------------------------------------ 区域相邻

    @app.get("/regions", response_class=HTMLResponse)
    def regions_page(request: Request, c: Container = Depends(get_container)):
        centers = c.centers.all()
        regions = sorted({x.region for x in centers if x.region})
        raw = _load_adjacency(c)
        return render(request, "regions.html", regions=regions,
                      adjacency=normalize_adjacency(raw), raw=raw,
                      by_region={r: [x.name for x in centers if x.region == r]
                                 for r in regions})

    @app.post("/regions")
    def save_adjacency(region: str = Form(...), neighbours: str = Form(""),
                       c: Container = Depends(get_container)):
        raw = _load_adjacency(c)
        raw[region] = [x.strip() for x in neighbours.replace("，", ",").split(",")
                       if x.strip()]
        _save_adjacency(c, raw)
        return RedirectResponse("/regions", status_code=303)

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
        extra = {"grid": None, "unplaced": [], "placed": 0, "total": 0}
        if task.output_path and Path(task.output_path).exists():
            extra.update(_read_workbook(task.output_path))
            detail = extra.get("detail")
            extra["total"] = len(detail["body"]) if detail else 0
            extra["placed"] = extra["total"] - len(extra["unplaced"])
        return render(request, "task.html", task=task, **extra)

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

    def _solve_in_background(task_id: str) -> None:
        """后台跑一次完整的排班：读表 → 求解 → 体检 → 写 xlsx。

        求解可能几分钟不收敛，所以不能在请求里做。异常一律记到任务上，
        不要让线程池吞掉 —— 任务永远停在「求解中」比报错更难查。
        """
        c = app.state.container
        task = c.tasks.get(task_id)
        if task is None:
            return
        try:
            problem = BuildProblem()(
                task.input_path, CONFIG_PATH,
                season=Season(task.season),
                centers_repo=c.centers, instructors_repo=c.instructors,
                calendar_repo=c.calendars)
            problem.campus_caps = _load_caps(c)
            problem.region_adjacency = normalize_adjacency(_load_adjacency(c))
        except Exception as exc:                       # noqa: BLE001
            task.status = TaskStatus.FAILED
            task.error = "读输入失败 —— %s: %s" % (type(exc).__name__, exc)
            task.finished_at = datetime.now()
            c.tasks.update(task)
            return

        out = c.data_dir / "outputs" / ("%s.xlsx" % task_id)
        out.parent.mkdir(parents=True, exist_ok=True)
        c.run_solve(task, problem, out)

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
        else:
            # 没有团队清单就没得排。明说，别让任务卡在「排队中」等一个
            # 永远不会来的求解。
            task.status = TaskStatus.FAILED
            task.error = "没有上传团队清单，无法排班。请上传一份 xlsx 后重建任务。"
            task.finished_at = datetime.now()
        c.tasks.create(task)
        if task.input_path:
            _pool.submit(_solve_in_background, task.id)
        return RedirectResponse("/tasks/%s" % task.id, status_code=303)

    @app.post("/tasks/demo")
    def create_demo_task(c: Container = Depends(get_container)):
        """一键跑示例：现造一份模拟清单，直接开算。

        结构照着真实那份表来（文学楼只上文学美育、S7 没有物理化学、
        指导员以单产品为主），规模砍过 —— demo 要的是点开就看到结果。
        """
        data = DemoDataset()
        task = SolveTask(id=uuid.uuid4().hex[:12],
                         name="示例排班 " + datetime.now().strftime("%m-%d %H:%M"),
                         season=Season.寒暑假.value)
        dest = c.data_dir / "uploads" / ("%s-示例清单.xlsx" % task.id)
        dest.parent.mkdir(parents=True, exist_ok=True)
        n_centers, n_inst, n_teams = data.write(dest)
        task.input_path = str(dest)
        task.notes = ["模拟数据：%d 个中心、%d 位指导员、%d 个团队。"
                      "结构照真实表，名字全是编的。" % (n_centers, n_inst, n_teams)]
        c.tasks.create(task)
        _pool.submit(_solve_in_background, task.id)
        return RedirectResponse("/tasks/%s" % task.id, status_code=303)

    @app.post("/tasks/{task_id}/rerun")
    def rerun(task_id: str, c: Container = Depends(get_container)):
        task = c.tasks.get(task_id)
        if task is None or not task.input_path:
            raise HTTPException(404, "没有这个任务，或者它没有输入文件")
        task.status = TaskStatus.PENDING
        task.error = ""
        task.notes = []
        c.tasks.update(task)
        _pool.submit(_solve_in_background, task_id)
        return RedirectResponse("/tasks/%s" % task_id, status_code=303)

    @app.get("/tasks/{task_id}/board", response_class=HTMLResponse)
    def board(request: Request, task_id: str,
              c: Container = Depends(get_container)):
        """看板：行 = 校区，列 = 期位 × 时段。不下载 xlsx 也能看结果。"""
        task = c.tasks.get(task_id)
        if task is None:
            raise HTTPException(404, "没有这个任务")
        if not task.output_path or not Path(task.output_path).exists():
            return render(request, "board.html", task=task, grid=None)
        return render(request, "board.html", task=task,
                      **_read_workbook(task.output_path))

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
