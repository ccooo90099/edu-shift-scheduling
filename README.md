# 排班系统

深圳某教培机构的自动排课工具。把「人在 Excel 里手工把两百多个班拖进时段格子」这件事反过来做：
**给定要开的课、可用的指导员、规则，自动排出课表**，并产出看板和冲突报告。

## 文档

| 文档 | 看什么 |
|---|---|
| [`docs/业务理解.md`](docs/业务理解.md) | **先看这份**。业务规则的精简版，只写结论 |
| [`docs/业务需求.md`](docs/业务需求.md) | 完整版：数据证据、推导过程、缺陷清单、状态清单 |
| [`docs/架构与功能逻辑.md`](docs/架构与功能逻辑.md) | 技术方案、模块职责、施工计划 |
| [`AGENTS.md`](AGENTS.md) | Claude / Codex 协作规则 |

## 形态

**公司内网网页 + 后端服务**。不做认证——内网部署，谁能访问谁能用。

```
FastAPI + Jinja2 + HTMX   无 SPA、无 Node 工具链
SQLite + 文件系统          单机内网，并发个位数
Docker                     内网服务器起一个容器
```

> 桌面端（PySide6 两端 + Ed25519 授权）已归档到 [`legacy/`](legacy/README.md)，不再维护。

## 目录

```
src/scheduling/            分层架构，依赖方向自外向内
  domain/                  领域层 —— 零框架依赖，有自动化断言守着
    model/                 时段、时段表、课程体系、期位、人群与报读组合、
                           团队、指导员、场地、学年日历
    policy/                连堂三档、转场口径、降级链、黄金时段、权重
    service/               排班问题与评分、体检、数据就绪度
    repository.py          仓储接口（Protocol），依赖倒置的边界
  application/             用例编排 —— CLI 与网页共用的唯一通道
    use_cases/             建问题、跑求解、体检、就绪度检查
  infrastructure/          实现领域定义的接口
    persistence/sqlite.py  四个仓储
    solver/cpsat.py        CP-SAT 适配（不含任何业务规则）
    spreadsheet/           xlsx 读入与导出
    maps/                  坐标系换算、通行时间表、地图 provider
  interfaces/web/          FastAPI + Jinja2 + HTMX

tools/                     命令行入口，与网页走同一条应用层
config/                    规则与数据表（真实文件不入库）
tests/                     domain / solver / infrastructure / web / 端到端
legacy/                    已归档：桌面端、授权体系、绑定旧模型的实验脚本
```

### 为什么这样分

业务规则经过十几轮澄清，期间推翻过 7 条推断。多数错误形式一样：
**某个业务概念在代码里是字符串或元组，于是两处对它的理解可以悄悄分叉。**
转场次数两处各自实现（同一份排班报出 19 和 25）、学生撮用年级推全科
（把刚降级的约束从后门放回来）、未知坐标系静默当 WGS-84（偏几百米不报错）。

所以分层的价值不在好看，在于**把业务语言变成构造期就能挡住错误的类型**。
详见 [`src/scheduling/domain/README.md`](src/scheduling/domain/README.md)。

## 跑起来

### 本地开发

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest

# 命令行
python tools/health_check.py 排班明细.xlsx --config config/rules.example.yaml
python tools/schedule.py 团队清单.xlsx --out 排班.xlsx --time-limit 120

# 网页
PYTHONPATH=src uvicorn scheduling.interfaces.web.app:create_app --factory --reload
```

### 内网部署

```bash
# 先放一份 htmx（仓库里没有，见 src/scheduling/interfaces/web/static/README.md）
curl -o src/scheduling/interfaces/web/static/htmx.min.js \
  https://cdnjs.cloudflare.com/ajax/libs/htmx/1.9.12/htmx.min.js

cp config/rules.example.yaml config/rules.yaml
docker compose up -d --build
```

完整说明见 [`docs/部署.md`](docs/部署.md)，含首次部署要补的三样数据。

### 公网 demo

最快的一条（不用注册任何账号）：

```bash
docker compose up -d --build
cloudflared tunnel --url http://localhost:8000    # 打印一个公网网址
```

想要固定网址的话用 Render 免费档（`render.yaml` 已备好）。
两条路的步骤、限制与对比见 [`docs/公网部署.md`](docs/公网部署.md)。

**演示实例只放虚构数据** —— 访问只隔着一个共享口令，不是认证。

> ⚠️ Dockerfile 与 compose 文件**从未真正构建运行过**（开发环境无 Docker
> daemon），只验证了镜像内那两条命令在容器外成立。首次部署请按文档逐项确认。

### 准备地理数据

各跑一次，之后排班完全离线、不需要网络也不需要 key：

```bash
python tools/geocode_centers.py    # 默认 OSM，免 key
python tools/travel_matrix.py
```

反查不到的在网页「中心」页手动补：选**地图来源**，粘经纬度。
不用管坐标系 —— 高德腾讯是 GCJ-02、百度是 BD-09、天地图和 OSM 是 WGS-84，
在深圳两两差 300–700 米，系统按来源自己折算，来源认不出就报错不猜。

## 数据安全

原始表含 106 位真实指导员姓名和门店信息，**不入库**。
`.gitignore` 覆盖 `*.xlsx`、`config/rules.yaml`、`config/centers.csv`、`config/travel.csv`、`secrets/`。
