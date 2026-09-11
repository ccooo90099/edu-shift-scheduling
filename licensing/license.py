"""许可文件的签发与校验。

结构：
    {"payload": {...业务字段...}, "alg": "ed25519", "sig": "<base64>"}

签名对象是 payload 的规范化 JSON（键排序、无空格、UTF-8），
所以任何字段被改一个字符，验签立刻失败。
"""
import base64
import json
from datetime import datetime, timedelta, timezone

from cryptography.exceptions import InvalidSignature

from .keys import ALG

VERSION = 1
CLOCK_SKEW = timedelta(hours=24)      # 容忍客户端时钟偏差


class LicenseError(Exception):
    """许可不可用。message 是可以直接显示给用户的中文原因。"""


def canonical(payload):
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def _parse_time(value, field):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        raise LicenseError("许可文件损坏：%s 不是合法时间" % field)


def issue(private_key, *, lic_id, issued_to, expires_at, seats=1,
          machines=None, features=None, limits=None, notes=""):
    """管理端签发一张许可。machines 为空 = 不绑定设备。"""
    payload = {
        "v": VERSION,
        "lic_id": lic_id,
        "issued_to": issued_to,
        "issued_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "expires_at": expires_at,
        "seats": int(seats),
        "machines": sorted(machines or []),
        "features": sorted(features or []),
        "limits": limits or {},
        "notes": notes,
    }
    sig = private_key.sign(canonical(payload))
    return {"payload": payload, "alg": ALG,
            "sig": base64.b64encode(sig).decode("ascii")}


def verify(public_key, document, *, fingerprint=None, now=None,
           required_feature=None):
    """用户端校验。通过返回 payload，否则抛 LicenseError。"""
    if not isinstance(document, dict) or "payload" not in document:
        raise LicenseError("许可文件格式不对")
    if document.get("alg") != ALG:
        raise LicenseError("不支持的签名算法：%s" % document.get("alg"))

    payload = document["payload"]
    try:
        public_key.verify(base64.b64decode(document.get("sig", "")),
                          canonical(payload))
    except (InvalidSignature, ValueError, TypeError):
        raise LicenseError("许可文件签名无效——可能被改过，或不是本产品签发的")

    if payload.get("v") != VERSION:
        raise LicenseError("许可版本 %s 不被这个版本的程序支持" % payload.get("v"))

    now = now or datetime.now(timezone.utc)
    issued = _parse_time(payload["issued_at"], "issued_at")
    expires = _parse_time(payload["expires_at"], "expires_at")
    if now + CLOCK_SKEW < issued:
        raise LicenseError("许可的签发时间还没到，请检查本机系统时间")
    if now - CLOCK_SKEW > expires:
        raise LicenseError("许可已于 %s 到期" % expires.date())

    machines = payload.get("machines") or []
    if machines and fingerprint not in machines:
        raise LicenseError("这台设备不在授权范围内（本机指纹 %s）" % fingerprint)

    if required_feature and required_feature not in (payload.get("features") or []):
        raise LicenseError("当前许可不含「%s」功能" % required_feature)

    return payload


def days_left(payload, now=None):
    now = now or datetime.now(timezone.utc)
    return (_parse_time(payload["expires_at"], "expires_at") - now).days


def load(path):
    with open(path, encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            raise LicenseError("许可文件不是合法的 JSON")


def dump(document, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(document, f, ensure_ascii=False, indent=2)
        f.write("\n")
