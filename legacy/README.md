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
