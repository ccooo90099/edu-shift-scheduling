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
engine/     求解内核，不依赖任何 UI
  slots.py      时段代数（重叠、并发组、课间阈值推导）
  travel.py     转场时间/距离判定，来源优先级与保守兜底
  inputs.py     从明细表派生团队 / 指导员 / 教室
  solver.py     CP-SAT 建模与求解
  health.py     体检：对任意一份排班算违规和得分
  output.py     写出 xlsx（5 个 sheet）
  mapapi.py     地图适配（OSM 默认免 key / 高德）
  coords.py     WGS-84 ↔ GCJ-02 坐标转换
  data.py       读配置、读排班、派生校区

tools/      命令行入口
  health_check.py     体检一份排班
  schedule.py         求解排班
  geocode_centers.py  地址 → 经纬度，写回 centers.csv
  travel_matrix.py    两两驾车时间/里程 → travel.csv

config/     规则与数据表（真实文件不入库，见 .gitignore）
tests/      测试
legacy/     已归档的桌面端与授权体系
```

## 跑起来

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest

python tools/health_check.py --help
python tools/schedule.py --help
```

准备地理数据（各跑一次，之后排班完全离线、不需要网络也不需要 key）：

```bash
python tools/geocode_centers.py    # 默认走 OSM，免 key
python tools/travel_matrix.py
```

## 数据安全

原始表含 106 位真实指导员姓名和门店信息，**不入库**。
`.gitignore` 覆盖 `*.xlsx`、`config/rules.yaml`、`config/centers.csv`、`config/travel.csv`、`secrets/`。
