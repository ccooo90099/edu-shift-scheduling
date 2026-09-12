"""授权层的测试 —— 重点是"篡改必须被抓出来"。"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from licensing import keys, license as lic   # noqa: E402


@pytest.fixture
def key():
    return keys.generate()


def make(key, **kw):
    kw.setdefault("lic_id", "LIC-TEST")
    kw.setdefault("issued_to", "测试团队")
    kw.setdefault("expires_at",
                  (datetime.now(timezone.utc) + timedelta(days=30)).isoformat())
    return lic.issue(key, **kw)


def test_签发的许可能通过校验(key):
    doc = make(key, features=["solver"])
    payload = lic.verify(key.public_key(), doc, required_feature="solver")
    assert payload["issued_to"] == "测试团队"


def test_改任何一个字段都会被抓出来(key):
    doc = make(key)
    doc["payload"]["issued_to"] = "别人"
    with pytest.raises(lic.LicenseError, match="签名无效"):
        lic.verify(key.public_key(), doc)


def test_偷偷延长有效期会被抓出来(key):
    doc = make(key)
    doc["payload"]["expires_at"] = "2099-01-01T00:00:00+00:00"
    with pytest.raises(lic.LicenseError, match="签名无效"):
        lic.verify(key.public_key(), doc)


def test_别人的私钥签的许可不认(key):
    doc = make(keys.generate())
    with pytest.raises(lic.LicenseError, match="签名无效"):
        lic.verify(key.public_key(), doc)


def test_过期的许可不认(key):
    doc = make(key, expires_at=(datetime.now(timezone.utc) - timedelta(days=2)).isoformat())
    with pytest.raises(lic.LicenseError, match="到期"):
        lic.verify(key.public_key(), doc)


def test_刚过期一小时的仍然可用_容忍时钟偏差(key):
    doc = make(key, expires_at=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat())
    assert lic.verify(key.public_key(), doc)


def test_把系统时间调到签发日之前会被拒(key):
    doc = make(key)
    past = datetime.now(timezone.utc) - timedelta(days=10)
    with pytest.raises(lic.LicenseError, match="系统时间"):
        lic.verify(key.public_key(), doc, now=past)


def test_设备绑定生效(key):
    doc = make(key, machines=["aaaa111122223333"])
    assert lic.verify(key.public_key(), doc, fingerprint="aaaa111122223333")
    with pytest.raises(lic.LicenseError, match="不在授权范围"):
        lic.verify(key.public_key(), doc, fingerprint="bbbb444455556666")


def test_不绑定设备时任意机器都可用(key):
    doc = make(key, machines=[])
    assert lic.verify(key.public_key(), doc, fingerprint="随便什么指纹")


def test_功能档位生效(key):
    doc = make(key, features=["health_check"])
    assert lic.verify(key.public_key(), doc, required_feature="health_check")
    with pytest.raises(lic.LicenseError, match="不含"):
        lic.verify(key.public_key(), doc, required_feature="solver")


def test_规范化序列化与键顺序无关(key):
    doc = make(key)
    reordered = json.loads(json.dumps(doc["payload"]))
    doc["payload"] = dict(reversed(list(reordered.items())))
    assert lic.verify(key.public_key(), doc)


def test_公钥可以在base64和对象之间来回转(key):
    text = keys.public_to_b64(key.public_key())
    doc = make(key)
    assert lic.verify(keys.public_from_b64(text), doc)


def test_坏掉的文件报中文原因(key):
    with pytest.raises(lic.LicenseError, match="格式不对"):
        lic.verify(key.public_key(), {"nope": 1})
