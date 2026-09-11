# edu-shift-scheduling · 排班小工具

把「人工在 Excel 里手工拖排班」变成「输入约束 → 自动生成排班表 + 看板 + 冲突报告」。

## 现在能用的

**排班体检** —— 按配置的口径检查一份现有排班，输出违规清单和基线分。

```bash
pip install -r requirements.txt
cp config/rules.example.yaml config/rules.yaml      # 改规则只改这个文件
cp config/centers.example.csv config/centers.csv    # 补上 30 个中心的经纬度

python tools/health_check.py 排班明细.xlsx \
       --config config/rules.yaml --out 违规清单.csv
```

输出长这样：

```
硬约束
  H1 老师同时段撞车     ✓ 0
  H2 同撮学生撞产品     ✕   （316 对撞车，涉及 407 / 661 个团队，62%）
  H3 教室同时段撞车     ✓ 0

连堂（S1）
  编程双语连堂         [硬]  中间不夹别的课 81/135（60%）；其中等待 ≤30 分钟的 51（38%）

老师跑场（S2 / S3）
  跨中心转场 96 次，赶路时间不够的 24 次
  转场总里程约 985 km，平均每次 10.3 km
```

## 目录

| 路径 | 内容 |
|---|---|
| `docs/需求理解.md` | 需求文档：数据模型、硬/软约束、现状基线、待办 |
| `config/rules.example.yaml` | 规则配置（冲突口径 / 连堂 / 地理 / 权重） |
| `config/centers.example.csv` | 30 个中心的坐标表模板，**待补经纬度** |
| `tools/health_check.py` | 排班体检 |
| `analysis/explore_source.py` | 源表探查，用来摸新数据的底 |

## 数据

源表含真实姓名与门店信息，不入库。`config/rules.yaml`、`config/centers.csv`、
`config/travel_minutes.csv` 同样已在 `.gitignore` 里——仓库里只留 `.example` 模板。
