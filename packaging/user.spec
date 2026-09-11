# -*- mode: python ; coding: utf-8 -*-
"""用户端打包配置。onedir 模式——PySide6 的 onefile 每次启动都要解压，太慢。"""
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
NAME = "EduShift"

a = Analysis(
    [str(ROOT / "apps" / "user" / "main.py")],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "config" / "rules.example.yaml"), "config")],
    hiddenimports=["pandas", "openpyxl", "yaml", "cryptography"],
    excludes=["tkinter", "matplotlib", "pytest", "PySide6.QtWebEngineCore"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=NAME,
          console=False, disable_windowed_traceback=False,
          target_arch=None, codesign_identity=None, entitlements_file=None)

coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name=NAME)

if sys.platform == "darwin":
    app = BUNDLE(coll, name=NAME + ".app",
                 bundle_identifier="com.edushift.scheduling",
                 info_plist={"NSHighResolutionCapable": True,
                             "CFBundleDisplayName": "排班助手"})
