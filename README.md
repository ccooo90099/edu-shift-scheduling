# edu-shift-scheduling · 排班助手

把「人工在 Excel 里手工拖排班」变成「输入约束 → 自动生成排班表 + 看板 + 冲突报告」。
跨平台桌面应用，分用户端和管理端两个产物。

## 现状

| 模块 | 状态 |
|---|---|
| 需求与约束梳理 | ✅ [`docs/需求理解.md`](docs/需求理解.md) |
| 规则配置 schema | ✅ [`config/rules.example.yaml`](config/rules.example.yaml) |
| 排班体检引擎 | ✅ `engine/` + `tools/health_check.py` |
| 授权（签发 / 验证） | ✅ `licensing/` |
| 地图距离 / 驾车耗时 | ✅ `engine/mapapi.py`，默认免 key |
| 两端桌面应用 | ✅ `apps/user` `apps/admin`（公钥已钉死） |
| CI 三平台构建 | ✅ [`.github/workflows/build.yml`](.github/workflows/build.yml) |
| **自动排班求解器** | ⬜ 下一步 |
| 看板视图 | ⬜ |

## 两个端

| | 用户端 `EduShift` | 管理端 `EduShiftAdmin` |
|---|---|---|
| 给谁 | 排课员 | 管理员本人 |
| 密钥 | 只有公钥（构建时编译进去） | 持有私钥（口令加密存本机） |
| 功能 | 导入排班 → 体检 → 导出违规清单 | 生成密钥、签发许可、查台账 |

细节见 [`docs/桌面应用与授权.md`](docs/桌面应用与授权.md)，含授权机制能防什么、不能防什么。

## 开发

```bash
pip install -r requirements.txt -r requirements-dev.txt
QT_QPA_PLATFORM=offscreen pytest          # 81 项

python apps/user/main.py                  # 用户端
python apps/admin/main.py                 # 管理端
python apps/user/main.py --selftest       # 不开窗口，只验依赖和公钥
```

命令行版体检（不需要界面）：

```bash
cp config/rules.example.yaml config/rules.yaml     # 改规则只改这个文件
cp config/centers.example.csv config/centers.csv   # 补上 30 个中心的经纬度
python tools/health_check.py 排班明细.xlsx --config config/rules.yaml --out 违规清单.csv
```

管理端也有命令行版：

```bash
python tools/admin_license.py keygen --out-dir secrets
python tools/admin_license.py issue --to "福田分区排课组" --days 365 \
       --machines <机器指纹> --out 福田.lic
python tools/admin_license.py inspect 福田.lic
```

## 打包

```bash
python tools/embed_pubkey.py --key "<base64 公钥>"     # 只影响用户端
pyinstaller --noconfirm --clean packaging/user.spec
pyinstaller --noconfirm --clean packaging/admin.spec
```

CI 在 macOS arm64 / macOS Intel / Windows x64 三个平台各打两个端。
需要在仓库 Secret 里配 `LICENSE_PUBLIC_KEY_B64`（**只放公钥**）。

## 目录

| 路径 | 内容 |
|---|---|
| `docs/` | 需求理解、桌面应用与授权 |
| `config/` | 规则配置与中心坐标表的模板 |
| `engine/` | 排班引擎：时段运算、通行时间、体检 |
| `licensing/` | 密钥、许可签发与校验、机器指纹 |
| `apps/` | 两端界面 |
| `tools/` | 命令行：体检、签发许可、嵌公钥 |
| `packaging/` | PyInstaller spec |
| `tests/` | 81 项测试，含端到端授权链路与地图工具 |

## 数据与密钥

源表含真实姓名与门店信息，不入库。以下均在 `.gitignore`：
`config/rules.yaml`、`config/centers.csv`、`config/travel.csv`、
`secrets/`、`*.pem`、`*.lic`、`dist/`、`build/`。
