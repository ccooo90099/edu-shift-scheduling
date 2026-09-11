"""用户端的授权闸门 —— 这里只有公钥，没有、也不能有私钥。

PUBLIC_KEY_B64 由构建脚本在打包时写入（tools/embed_pubkey.py）。
仓库里留的是占位符，所以未经构建的源码跑不出有效授权，这是故意的。
"""
import os
import sys
from pathlib import Path

from .fingerprint import machine_fingerprint
from .keys import public_from_b64
from .license import LicenseError, days_left, load, verify

PUBLIC_KEY_B64 = "REPLACE_AT_BUILD_TIME"

APP_DIR_NAME = "EduShiftScheduling"


def app_data_dir():
    """各平台的标准用户数据目录，卸载重装不丢。"""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home()))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / APP_DIR_NAME


def license_path():
    override = os.environ.get("EDUSHIFT_LICENSE")
    return Path(override) if override else app_data_dir() / "license.lic"


def check(required_feature=None, path=None):
    """校验本机许可。通过返回 payload，否则抛 LicenseError（message 可直接显示）。"""
    if PUBLIC_KEY_B64 == "REPLACE_AT_BUILD_TIME":
        raise LicenseError("这是未经构建的开发版，没有嵌入公钥")

    path = Path(path) if path else license_path()
    if not path.exists():
        raise LicenseError("没找到许可文件，请把管理员发给你的 .lic 放到：\n%s" % path)

    return verify(public_from_b64(PUBLIC_KEY_B64), load(path),
                  fingerprint=machine_fingerprint(),
                  required_feature=required_feature)


def install(src, path=None):
    """把管理员发来的 .lic 装到标准位置；先验一遍，不合格的不落地。"""
    document = load(src)
    payload = verify(public_from_b64(PUBLIC_KEY_B64), document,
                     fingerprint=machine_fingerprint())
    path = Path(path) if path else license_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    from .license import dump
    dump(document, path)
    return payload


def status_line(payload):
    left = days_left(payload)
    who = payload.get("issued_to", "—")
    if left < 0:
        return "授权已过期 · %s" % who
    if left <= 30:
        return "授权剩余 %d 天 · %s" % (left, who)
    return "已授权 · %s · 有效期至 %s" % (who, payload["expires_at"][:10])
