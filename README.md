# edu-shift-scheduling · 排班小工具

把「人工在 Excel 里手工拖排班」变成「输入约束 → 自动生成排班表 + 看板 + 冲突报告」。

## 当前状态

需求梳理阶段。**先看 [`docs/需求理解.md`](docs/需求理解.md)** —— 里面有数据模型、约束清单、
现状基线，以及 8 个需要先对齐的问题（Q1/Q2/Q3 不定下来就没法开工）。

## 目录

| 路径 | 内容 |
|---|---|
| `docs/需求理解.md` | 需求理解文档（v0.1） |
| `analysis/explore_source.py` | 源表探查脚本，文档里所有统计数字由它产出 |

```bash
pip install pandas openpyxl
python analysis/explore_source.py 排班明细.xlsx [sheet名]
```

> 源表含真实姓名与门店信息，不入库；开发请用脱敏样例，字段结构见需求文档 §1.2。
