---
title: 排班系统 Demo
emoji: 📅
colorFrom: blue
colorTo: gray
sdk: docker
app_port: 8000
pinned: false
---

# 排班系统 · 演示

教培机构自动排课工具的演示实例。

**访问需要口令。** 口令由部署者在 Space 的 Secrets 里设置
（`SCHEDULING_PASSWORD`）。

## ⚠️ 这是演示环境

- **数据全是编的。** 中心名、地址、指导员姓名都是虚构的示例，
  不对应任何真实门店或真人。
- **重启会清空。** Hugging Face Spaces 免费档的文件系统是临时的，
  Space 重建或休眠唤醒后，上传的文件和配置都会没，
  系统会自动重灌一份示例数据。
- **不要往这里放真实数据。** 访问只隔着一个共享口令，不是认证。

源码与文档：https://github.com/ccooo90099/edu-shift-scheduling

---

> **注：Hugging Face 的 Docker Space 现在需要付费**（2026-09 用户实测）。
> 这个目录留着，万一以后又免费了可以直接用。
> 当前推荐的免费方案见 [`../../docs/公网部署.md`](../../docs/公网部署.md)。
