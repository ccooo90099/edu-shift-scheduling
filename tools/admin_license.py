#!/usr/bin/env python3
"""管理端授权工具 —— 生成密钥、签发许可、查看许可。

    python tools/admin_license.py keygen  --out-dir secrets
    python tools/admin_license.py issue   --key secrets/admin_private.pem \
           --to "福田分区排课组" --days 365 --machines 69bf7da67bfdd561 \
           --features solver,export --out 福田.lic
    python tools/admin_license.py inspect 福田.lic --pubkey secrets/admin_public.pem

私钥文件绝不能进仓库，也绝不能随用户端分发。
"""
import argparse
import getpass
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from licensing import keys, license as lic   # noqa: E402

ALL_FEATURES = ["health_check", "solver", "board", "export"]


def cmd_keygen(args):
    os.makedirs(args.out_dir, exist_ok=True)
    priv_path = os.path.join(args.out_dir, "admin_private.pem")
    pub_path = os.path.join(args.out_dir, "admin_public.pem")
    if os.path.exists(priv_path) and not args.force:
        sys.exit("已存在 %s。覆盖会让所有已签发的许可作废——确定就加 --force" % priv_path)

    passphrase = args.passphrase or getpass.getpass("给私钥设一个口令：")
    if not args.passphrase and passphrase != getpass.getpass("再输一次："):
        sys.exit("两次口令不一致")

    key = keys.generate()
    keys.save_private(key, priv_path, passphrase)
    keys.save_public(key.public_key(), pub_path)

    print("私钥  %s   ← 离线备份，绝不外发、绝不进仓库" % priv_path)
    print("公钥  %s" % pub_path)
    print("\n嵌进用户端的公钥串：")
    print("  " + keys.public_to_b64(key.public_key()))


def cmd_issue(args):
    passphrase = args.passphrase or getpass.getpass("私钥口令：")
    try:
        key = keys.load_private(args.key, passphrase)
    except (ValueError, TypeError):
        sys.exit("私钥口令不对，或文件损坏")

    expires = (datetime.now(timezone.utc) + timedelta(days=args.days)
               ).replace(microsecond=0).isoformat()
    features = [f.strip() for f in args.features.split(",") if f.strip()] \
        if args.features else ALL_FEATURES
    unknown = set(features) - set(ALL_FEATURES)
    if unknown:
        sys.exit("未知功能项：%s（可选 %s）" % ("、".join(sorted(unknown)), "、".join(ALL_FEATURES)))

    machines = [m.strip() for m in (args.machines or "").split(",") if m.strip()]
    document = lic.issue(
        key,
        lic_id=args.lic_id or "LIC-%s" % datetime.now().strftime("%Y%m%d-%H%M%S"),
        issued_to=args.to, expires_at=expires, seats=args.seats,
        machines=machines, features=features, notes=args.notes or "")
    lic.dump(document, args.out)

    p = document["payload"]
    print("已签发 %s → %s" % (p["lic_id"], args.out))
    print("  客户   %s" % p["issued_to"])
    print("  到期   %s（%d 天）" % (p["expires_at"][:10], args.days))
    print("  功能   %s" % "、".join(p["features"]))
    print("  设备   %s" % ("、".join(p["machines"]) if p["machines"] else "不绑定（任意设备可用）"))


def cmd_inspect(args):
    document = lic.load(args.file)
    public = keys.load_public(args.pubkey)
    try:
        payload = lic.verify(public, document, fingerprint=args.fingerprint)
    except lic.LicenseError as e:
        print("✕ %s" % e)
        print("\n（若只是本机不在白名单，许可本身可能仍然有效）")
        sys.exit(1)
    print("✓ 签名有效，剩余 %d 天" % lic.days_left(payload))
    for k, v in payload.items():
        print("  %-11s %s" % (k, v))


def main():
    ap = argparse.ArgumentParser(description="管理端授权工具")
    sub = ap.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("keygen", help="生成一对密钥（一次性）")
    g.add_argument("--out-dir", default="secrets")
    g.add_argument("--passphrase", help="非交互用；平时留空走提示输入")
    g.add_argument("--force", action="store_true")
    g.set_defaults(func=cmd_keygen)

    i = sub.add_parser("issue", help="签发一张许可")
    i.add_argument("--key", default="secrets/admin_private.pem")
    i.add_argument("--passphrase")
    i.add_argument("--to", required=True, help="发给谁（客户/团队名）")
    i.add_argument("--days", type=int, default=365)
    i.add_argument("--seats", type=int, default=1)
    i.add_argument("--machines", help="机器指纹，逗号分隔；留空=不绑定设备")
    i.add_argument("--features", help="逗号分隔，默认全开：%s" % "、".join(ALL_FEATURES))
    i.add_argument("--lic-id")
    i.add_argument("--notes")
    i.add_argument("--out", required=True)
    i.set_defaults(func=cmd_issue)

    s = sub.add_parser("inspect", help="查看/校验一张许可")
    s.add_argument("file")
    s.add_argument("--pubkey", default="secrets/admin_public.pem")
    s.add_argument("--fingerprint", help="按这个指纹校验设备绑定")
    s.set_defaults(func=cmd_inspect)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
