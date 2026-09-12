# 归档：桌面端与授权体系

这些代码**不再维护**，保留仅为历史可查。

## 为什么归档

交付形态由「跨端桌面应用 + 授权管理」改为「**公司内网网页 + 后端服务**」。
内网部署不做认证（用户定案：谁能访问谁能用），因此整套授权体系在新架构下没有位置——
不是暂缓，是不用了。详见 [`../docs/架构与功能逻辑.md`](../docs/架构与功能逻辑.md) §0。

## 归档了什么

| 路径 | 原位置 | 内容 |
|---|---|---|
| `apps/` | `apps/` | PySide6 用户端与管理端 |
| `packaging/` | `packaging/` | PyInstaller 打包配置 |
| `licensing/` | `licensing/` | Ed25519 签发与校验、机器指纹 |
| `tests/` | `tests/test_{apps_smoke,licensing,end_to_end_license,pinned_key}.py` | 对应测试 |
| `tools_admin_license.py` | `tools/admin_license.py` | 命令行签发 |
| `tools_embed_pubkey.py` | `tools/embed_pubkey.py` | 公钥固化 |

## 一并解决的一个长期 CI 红灯

macOS Intel 的产物自检长期崩溃：

```
Symbol not found: _SSL_get0_group_name
  Referenced from: cryptography/hazmat/bindings/_rust.abi3.so
  Expected in:     Frameworks/libssl.3.dylib
```

PyInstaller 打进 app 的 `libssl.3.dylib` 与 `cryptography` 的 Rust 扩展所链接的
OpenSSL 版本不匹配。只在 `macos-15-intel` 上出现，arm64 与 Windows 均通过。
桌面端停止构建后此 job 不再存在，问题随之消失——**未修复，只是不再触发**。
若将来恢复桌面端构建，这个坑还在。

## 引擎没有被归档

`engine/` 从第一天起就不 import 任何 UI，所以形态变更不需要重写内核。
桌面端怎么用它，网页端原样复用。

## analysis/ 里的两个实验脚本

`legacy/analysis/h2_soft_proxy_experiment.py` 与 `fixed_slot_transfer_experiment.py`
是 Codex 与 Claude 交叉验证期间的诊断脚本，**绑定在已被替换的 `engine/` 模型上**：

- 它们跑的是「H2 为硬约束、教室按时段标签计数」的旧模型
- `h2_soft_proxy_experiment.py` 自带基线检查，engine 一变就拒绝以旧模型名义运行

`engine/` 已被 `src/scheduling/` 取代，所以这两个脚本**跑不起来了**，保留仅为
让 `analysis/results/` 里的历史结果可追溯到产生它的代码。

⚠️ 那批结果（如段次3 的 20 次转场）是在**故意保留 R10/R11 两个缺陷**的模型上
跑出来的，用于隔离 H2 这一个变量。**不能当作交付排班，也不能与新模型的
结果直接比较。**
