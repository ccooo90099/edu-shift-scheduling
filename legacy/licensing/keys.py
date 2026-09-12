"""密钥管理 —— 私钥只在管理端，公钥随用户端一起发布。

    管理端：keygen 一次，生成 admin_private.pem（口令加密）+ admin_public.pem
    用户端：构建时把 admin_public.pem 的内容编译进去，运行时只做验签

私钥一旦泄露，等于任何人都能签发许可；一旦丢失，已发出的许可仍然有效，
但再也签不出新的。所以它要离线备份，并且和用户端代码分仓管理。
"""
import base64
import os

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey)

ALG = "ed25519"


def generate():
    return Ed25519PrivateKey.generate()


def save_private(key, path, passphrase):
    """私钥落盘一律口令加密，不给"就先不加密"的选项。"""
    if not passphrase:
        raise ValueError("私钥必须设口令")
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.BestAvailableEncryption(
            passphrase.encode("utf-8")))
    with open(path, "wb") as f:
        f.write(pem)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass          # Windows 上没有 chmod，忽略


def load_private(path, passphrase):
    with open(path, "rb") as f:
        return serialization.load_pem_private_key(
            f.read(), password=passphrase.encode("utf-8"))


def save_public(key, path):
    pem = key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo)
    with open(path, "wb") as f:
        f.write(pem)


def load_public(path):
    with open(path, "rb") as f:
        return serialization.load_pem_public_key(f.read())


def public_to_b64(key):
    """32 字节裸公钥的 base64 —— 这是要嵌进用户端源码的那一串。"""
    raw = key.public_bytes(encoding=serialization.Encoding.Raw,
                           format=serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode("ascii")


def public_from_b64(text):
    return Ed25519PublicKey.from_public_bytes(base64.b64decode(text))
