"""网页层 —— 端到端。用 TestClient，不起真服务器。"""
import pytest
from fastapi.testclient import TestClient

from scheduling.application.dto import SolveTask, TaskStatus
from scheduling.domain.model.curriculum import product_of
from scheduling.domain.model.instructor import Instructor
from scheduling.domain.model.venue import Center, Datum
from scheduling.infrastructure.persistence.sqlite import (
    SqliteCalendarRepository, SqliteCenterRepository,
    SqliteInstructorRepository, SqliteTaskRepository, connect)
from scheduling.interfaces.web.app import create_app
from scheduling.interfaces.web.container import Container


@pytest.fixture
def app(tmp_path):
    conn = connect(tmp_path / "t.db")
    return create_app(Container(
        centers=SqliteCenterRepository(conn),
        instructors=SqliteInstructorRepository(conn),
        calendars=SqliteCalendarRepository(conn),
        tasks=SqliteTaskRepository(conn),
        data_dir=tmp_path))


@pytest.fixture
def client(app):
    return TestClient(app)


def test_首页能打开(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "排班任务" in r.text


def test_没有数据时顶部就挂着告警条(client):
    """缺坐标、缺资质都不会报错，只会让求解悄悄退化 —— 所以要一直喊。"""
    r = client.get("/")
    assert "还没填学年日历" in r.text
    assert "不管的话" in r.text, "告警必须说清后果，否则没人去补"


def test_告警条说明后果而不只是报状态(client):
    r = client.get("/api/readiness")
    codes = {i["code"] for i in r.json()}
    assert "calendar.empty" in codes
    assert all(i["consequence"] for i in r.json())


def test_补齐数据后告警消失(client):
    client.post("/centers", data={"name": "甲中心", "rooms": "2"})
    assert "1 个中心还没有坐标" in client.get("/").text
    client.post("/centers/甲中心/coordinate",
                data={"longitude": "114.06", "latitude": "22.54",
                      "map_source": "高德"})
    assert "还没有坐标" not in client.get("/").text


def test_坐标按地图来源定坐标系(client, app):
    client.post("/centers", data={"name": "甲中心"})
    client.post("/centers/甲中心/coordinate",
                data={"longitude": "114.06", "latitude": "22.54",
                      "map_source": "百度"})
    c = app.state.container.centers.get("甲中心")
    assert c.coordinate.datum is Datum.BD09, "百度是 BD-09，不是 GCJ-02"


def test_未知地图来源被拒绝而不是猜一个(client):
    client.post("/centers", data={"name": "甲中心"})
    r = client.post("/centers/甲中心/coordinate",
                    data={"longitude": "114.06", "latitude": "22.54",
                          "map_source": "某某地图"})
    assert r.status_code == 400
    assert "未知地图来源" in r.json()["detail"]


def test_中心页可按缺坐标筛选(client):
    client.post("/centers", data={"name": "有坐标"})
    client.post("/centers", data={"name": "没坐标"})
    client.post("/centers/有坐标/coordinate",
                data={"longitude": "114.0", "latitude": "22.5",
                      "map_source": "天地图"})
    body = client.get("/centers?filter=missing-coordinate").text
    assert "没坐标" in body and body.count("有坐标") <= 1


def test_指导员单个与批量编辑(client, app):
    client.post("/instructors", data={
        "name": "甲老师", "products": "编程理论,双语文化",
        "unavailable": "18:30-20:30", "max_sessions": "3"})
    i = app.state.container.instructors.get("甲老师")
    assert product_of("双语文化") in i.teachable
    assert i.max_sessions_per_day == 3

    client.post("/instructors/bulk",
                data={"names": "乙老师,丙老师", "products": "文学美育",
                      "max_sessions": "5"})
    for name in ("乙老师", "丙老师"):
        x = app.state.container.instructors.get(name)
        assert x.teachable == {product_of("文学美育")}
        assert x.max_sessions_per_day == 5


def test_未知产品被拒绝(client):
    r = client.post("/instructors", data={"name": "甲", "products": "不存在的课"})
    assert r.status_code == 400 and "未知产品" in r.json()["detail"]


def test_缺配置的指导员能筛出来(client):
    client.post("/instructors", data={"name": "配了的", "products": "编程理论"})
    client.post("/instructors", data={"name": "没配的"})
    body = client.get("/instructors?filter=unconfigured").text
    assert "没配的" in body


def test_建任务后跳到任务页(client):
    r = client.post("/tasks", data={"name": "段次3", "season": "寒暑假"},
                    follow_redirects=True)
    assert r.status_code == 200 and "段次3" in r.text


def test_进度片段在未结束时带轮询_结束后不带(client, app):
    """任务终结后返回的片段不再带 hx-* ，前端自然停下来。"""
    tasks = app.state.container.tasks
    t = SolveTask(id="t1", name="x", season="寒暑假", status=TaskStatus.RUNNING)
    tasks.create(t)
    assert "hx-trigger" in client.get("/tasks/t1/progress").text

    t.status = TaskStatus.DONE
    tasks.update(t)
    assert "hx-trigger" not in client.get("/tasks/t1/progress").text


def test_任务状态与求解状态分开显示(client, app):
    """任务「已完成」不代表解「最优」—— 把 FEASIBLE 说成排好了是误导。"""
    app.state.container.tasks.create(SolveTask(
        id="t2", name="x", season="寒暑假", status=TaskStatus.DONE,
        solver_status="FEASIBLE", objective=100.0, best_bound=80.0))
    data = client.get("/api/tasks/t2").json()
    assert data["status_label"] == "已完成"
    assert data["solver_status"] == "FEASIBLE"
    assert "未证明最优" in data["gap_hint"]

    body = client.get("/tasks/t2").text
    assert "FEASIBLE" in body and "未证明最优" in body


def test_不存在的任务返回404而不是500(client):
    assert client.get("/tasks/nope").status_code == 404
    assert client.get("/api/tasks/nope").status_code == 404


def test_没有产物时下载返回404(client, app):
    app.state.container.tasks.create(
        SolveTask(id="t3", name="x", season="寒暑假"))
    assert client.get("/tasks/t3/download").status_code == 404


# ── 教室数可配（用户补充）───────────────────────────────────

def test_教室数可以随时改_不只是新建时(client, app):
    """校区的教室是有限且已知的，后台要能直接填。"""
    client.post("/centers", data={"name": "甲中心", "rooms": "3"})
    assert app.state.container.centers.get("甲中心").room_count == 3

    client.post("/centers/甲中心/rooms", data={"count": "6"})
    c = app.state.container.centers.get("甲中心")
    assert c.room_count == 6
    assert not c.rooms_are_estimated, "人填的是实数，不是估计"


def test_留空教室数时不动原值(client, app):
    client.post("/centers", data={"name": "甲中心", "rooms": "5"})
    client.post("/centers", data={"name": "甲中心", "region": "福田"})
    c = app.state.container.centers.get("甲中心")
    assert c.room_count == 5, "只改区域不该把教室数清零"
    assert c.region == "福田"


def test_教室数填负数被拒(client):
    client.post("/centers", data={"name": "甲中心"})
    assert client.post("/centers/甲中心/rooms",
                       data={"count": "-1"}).status_code == 400


# ── 区域相邻（用户补充）─────────────────────────────────────

def test_区域相邻页列出所有区域并标出未配的(client):
    client.post("/centers", data={"name": "宝安甲", "region": "宝安"})
    client.post("/centers", data={"name": "南山甲", "region": "南山"})
    body = client.get("/regions").text
    assert "宝安" in body and "南山" in body
    assert "未配，一律按跨区域算" in body


def test_配了相邻关系后自动补成双向(client):
    client.post("/centers", data={"name": "宝安甲", "region": "宝安"})
    client.post("/centers", data={"name": "南山甲", "region": "南山"})
    client.post("/regions", data={"region": "宝安", "neighbours": "南山"})

    body = client.get("/regions").text
    assert "未配" not in body, "两边都该显示已配 —— 只写一边系统自动补反向"


def test_相邻表落盘后重启仍在(client, app, tmp_path):
    client.post("/centers", data={"name": "宝安甲", "region": "宝安"})
    client.post("/regions", data={"region": "宝安", "neighbours": "南山,福田"})
    assert (tmp_path / "region_adjacency.json").exists()

    from scheduling.interfaces.web.app import _load_adjacency
    assert _load_adjacency(app.state.container)["宝安"] == ["南山", "福田"]


# ── 场地容量两层（用户补充：教室数不一定，做成配置）──────────

def test_校区容量页列出各校区及其中心(client):
    client.post("/centers", data={"name": "百花科学", "campus": "百花", "rooms": "3"})
    client.post("/centers", data={"name": "百花文学", "campus": "百花", "rooms": "2"})
    body = client.get("/capacity").text
    assert "百花" in body
    assert "百花科学（3 间）" in body and "百花文学（2 间）" in body
    assert "只按各中心教室数" in body, "没配校区上限时要说明"


def test_设了校区上限后标出哪一层更严(client):
    client.post("/centers", data={"name": "百花科学", "campus": "百花", "rooms": "3"})
    client.post("/centers", data={"name": "百花文学", "campus": "百花", "rooms": "2"})
    client.post("/capacity", data={"campus": "百花", "cap": "2"})
    body = client.get("/capacity").text
    assert "校区上限更严" in body


def test_校区上限留空表示不设这一层(client, app):
    from scheduling.interfaces.web.app import _load_caps
    client.post("/centers", data={"name": "甲中心", "campus": "甲", "rooms": "3"})
    client.post("/capacity", data={"campus": "甲", "cap": "2"})
    assert _load_caps(app.state.container) == {"甲": 2}

    client.post("/capacity", data={"campus": "甲", "cap": ""})
    assert _load_caps(app.state.container) == {}, "留空 = 清掉这一层，不是设成 0"


def test_校区上限非法输入被拒(client):
    client.post("/centers", data={"name": "甲中心", "campus": "甲"})
    assert client.post("/capacity", data={"campus": "甲", "cap": "abc"}).status_code == 400
    assert client.post("/capacity", data={"campus": "甲", "cap": "-1"}).status_code == 400
