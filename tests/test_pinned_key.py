"""钉在源码里的那把公钥 —— 它错了，发出去的用户端就全是废的。

所以这几条不是可有可无的：它们守住的是"打出来的包能不能验签"。
"""
import base64
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from licensing import gate, keys, license as lic   # noqa: E402
from licensing.fingerprint import machine_fingerprint   # noqa: E402


def test_源码里钉的是一把真公钥_不是占位符():
    assert gate.PUBLIC_KEY_B64 != "REPLACE_AT_BUILD_TIME", (
        "公钥还是占位符 —— 这样打出来的用户端跑不起来")
    raw = base64.b64decode(gate.PUBLIC_KEY_B64, validate=True)
    assert len(raw) == 32, "Ed25519 公钥必须是 32 字节，实际 %d" % len(raw)
    assert keys.public_from_b64(gate.PUBLIC_KEY_B64)      # 能真的构造出来


def test_钉住的公钥不会被无意改掉():
    """改公钥 = 让所有已发出的许可作废，必须是有意为之。

    真要轮换密钥时，把下面这一行一起改掉。
    """
    assert gate.PUBLIC_KEY_B64 == "2TZKrGe+13zpR76T/pGV/C3Jw3iZLydYV10i5v+HqMY="


def test_别人私钥签的许可_钉住的公钥必须拒绝(tmp_path):
    """证明钉住的公钥真的在生效，而不是形同虚设。"""
    attacker = keys.generate()
    document = lic.issue(
        attacker, lic_id="LIC-FAKE", issued_to="伪造者",
        expires_at=(datetime.now(timezone.utc) + timedelta(days=999)).isoformat())
    path = tmp_path / "fake.lic"
    lic.dump(document, str(path))

    with pytest.raises(lic.LicenseError, match="签名无效"):
        gate.install(str(path), path=str(tmp_path / "installed.lic"))
    assert not (tmp_path / "installed.lic").exists()


def test_没装许可时用户端给的是可操作的提示(tmp_path):
    with pytest.raises(lic.LicenseError, match="没找到许可文件") as e:
        gate.check(path=str(tmp_path / "nothing.lic"))
    assert str(tmp_path) in str(e.value)       # 提示里要写清楚放哪


def test_本机指纹是稳定的():
    """指纹变了 = 绑了设备的许可全部失效，所以它必须稳定。"""
    a, b = machine_fingerprint(), machine_fingerprint()
    assert a == b
    assert len(a) == 16 and all(c in "0123456789abcdef" for c in a)
