#!/usr/bin/env python3
"""构建时把公钥写进用户端。

    python tools/embed_pubkey.py --key "<base64 公钥>"
    python tools/embed_pubkey.py --key "$LICENSE_PUBLIC_KEY_B64" --allow-missing

只动 licensing/gate.py 里 PUBLIC_KEY_B64 那一行。私钥永远不参与构建。
"""
import argparse
import base64
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from console import force_utf8   # noqa: E402

GATE = pathlib.Path(__file__).resolve().parent.parent / "licensing" / "gate.py"
PLACEHOLDER = "REPLACE_AT_BUILD_TIME"
PATTERN = re.compile(r'^PUBLIC_KEY_B64 = ".*"$', re.MULTILINE)


def main():
    force_utf8()
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", default="", help="Ed25519 公钥的 base64（32 字节裸公钥）")
    ap.add_argument("--allow-missing", action="store_true",
                    help="key 为空时不报错，保留占位符（产出的是跑不起来的开发版）")
    ap.add_argument("--verify", action="store_true",
                    help="只检查源码里是否已经钉死了公钥，不做修改。钉死返回 0，还是占位符返回 1")
    args = ap.parse_args()

    if args.verify:
        text = GATE.read_text(encoding="utf-8")
        match = PATTERN.search(text)
        if not match:
            sys.exit("在 %s 里找不到 PUBLIC_KEY_B64 这一行" % GATE)
        current = match.group(0).split('"')[1]
        if current == PLACEHOLDER:
            print("源码里还是占位符，没有钉死公钥")
            sys.exit(1)
        print("源码里已钉死公钥 %s…%s" % (current[:8], current[-6:]))
        return

    key = args.key.strip()
    if not key:
        if not args.allow_missing:
            sys.exit("没有提供公钥。设置仓库 Secret「LICENSE_PUBLIC_KEY_B64」，"
                     "或显式加 --allow-missing 产出开发版。")
        print("::warning::未提供公钥，用户端将保留占位符——这个产物无法通过授权校验。")
        return

    try:
        raw = base64.b64decode(key, validate=True)
    except (ValueError, TypeError):
        sys.exit("公钥不是合法的 base64")
    if len(raw) != 32:
        sys.exit("Ed25519 公钥应为 32 字节，实际 %d 字节" % len(raw))

    text = GATE.read_text(encoding="utf-8")
    if not PATTERN.search(text):
        sys.exit("在 %s 里找不到 PUBLIC_KEY_B64 这一行" % GATE)
    GATE.write_text(PATTERN.sub('PUBLIC_KEY_B64 = "%s"' % key, text), encoding="utf-8")
    print("已写入公钥 %s…%s" % (key[:8], key[-6:]))


if __name__ == "__main__":
    main()
