"""端到端：管理端生成密钥 → 签发许可 → 用户端导入并通过校验。

这条链是产品的命门，所以它有独立一条测试，不依赖界面。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from licensing import gate, keys, license as lic   # noqa: E402
from licensing.fingerprint import machine_fingerprint   # noqa: E402


@pytest.fixture
def admin_keys(tmp_path):
    """模拟管理员在自己机器上生成密钥对。"""
    priv_path = tmp_path / "admin_private.pem"
    key = keys.generate()
    keys.save_private(key, str(priv_path), "口令123")
    keys.save_public(key.public_key(), str(tmp_path / "admin_public.pem"))
    return key, priv_path


def test_私钥必须带口令才能打开(admin_keys, tmp_path):
    _, priv_path = admin_keys
    assert keys.load_private(str(priv_path), "口令123")
    with pytest.raises((ValueError, TypeError)):
        keys.load_private(str(priv_path), "错口令")


def test_签发到导入的完整链路(admin_keys, tmp_path, monkeypatch):
    key, priv_path = admin_keys

    # ① 管理端：从磁盘载入私钥，签发一张绑本机的许可
    loaded = keys.load_private(str(priv_path), "口令123")
    fingerprint = machine_fingerprint()
    document = lic.issue(loaded, lic_id="LIC-E2E", issued_to="端到端测试组",
                         expires_at="2099-01-01T00:00:00+00:00",
                         machines=[fingerprint], features=["health_check", "solver"])
    lic_file = tmp_path / "test.lic"
    lic.dump(document, str(lic_file))

    # ② 构建：把公钥嵌进用户端
    monkeypatch.setattr(gate, "PUBLIC_KEY_B64", keys.public_to_b64(key.public_key()))

    # ③ 用户端：导入许可，之后功能可用
    installed = tmp_path / "installed.lic"
    payload = gate.install(str(lic_file), path=str(installed))
    assert payload["issued_to"] == "端到端测试组"

    assert gate.check(path=str(installed))
    assert gate.check(required_feature="solver", path=str(installed))
    with pytest.raises(lic.LicenseError, match="不含"):
        gate.check(required_feature="board", path=str(installed))
    assert "端到端测试组" in gate.status_line(payload)


def test_用别的私钥签的许可装不进去(admin_keys, tmp_path, monkeypatch):
    key, _ = admin_keys
    attacker = keys.generate()
    document = lic.issue(attacker, lic_id="LIC-FAKE", issued_to="伪造",
                         expires_at="2099-01-01T00:00:00+00:00")
    fake = tmp_path / "fake.lic"
    lic.dump(document, str(fake))

    monkeypatch.setattr(gate, "PUBLIC_KEY_B64", keys.public_to_b64(key.public_key()))
    with pytest.raises(lic.LicenseError, match="签名无效"):
        gate.install(str(fake), path=str(tmp_path / "installed.lic"))
    assert not (tmp_path / "installed.lic").exists()      # 不合格的不落地


def test_改过的许可文件装不进去(admin_keys, tmp_path, monkeypatch):
    key, _ = admin_keys
    document = lic.issue(key, lic_id="LIC-X", issued_to="正常客户",
                         expires_at="2026-01-01T00:00:00+00:00")
    document["payload"]["expires_at"] = "2099-01-01T00:00:00+00:00"   # 偷偷续期
    tampered = tmp_path / "tampered.lic"
    lic.dump(document, str(tampered))

    monkeypatch.setattr(gate, "PUBLIC_KEY_B64", keys.public_to_b64(key.public_key()))
    with pytest.raises(lic.LicenseError, match="签名无效"):
        gate.install(str(tampered), path=str(tmp_path / "installed.lic"))


def test_没装许可时提示去哪放(monkeypatch, tmp_path):
    monkeypatch.setattr(gate, "PUBLIC_KEY_B64", keys.public_to_b64(keys.generate().public_key()))
    with pytest.raises(lic.LicenseError, match="没找到许可文件"):
        gate.check(path=str(tmp_path / "nothing.lic"))
