"""打包产物的自检 —— 不开窗口，只验证"这个二进制是完整的"。

验三件事：依赖能不能 import（pandas / Qt / cryptography 全都冻进去了没有）、
公钥有没有嵌进去、本机指纹能不能算出来。CI 打完包直接跑它。
"""
import sys


def run(app_name, needs_public_key, needs_engine=True):
    print("%s 自检" % app_name)
    print("  python      %s" % sys.version.split()[0])
    print("  frozen      %s" % getattr(sys, "frozen", False))

    from PySide6 import QtCore
    import cryptography
    print("  PySide6/Qt  %s" % QtCore.qVersion())
    print("  cryptography %s" % cryptography.__version__)
    if needs_engine:
        import pandas
        import yaml                                # noqa: F401
        print("  pandas      %s" % pandas.__version__)

    from licensing.fingerprint import machine_fingerprint
    print("  机器指纹     %s" % machine_fingerprint())

    from licensing.gate import PUBLIC_KEY_B64
    embedded = PUBLIC_KEY_B64 != "REPLACE_AT_BUILD_TIME"
    print("  公钥        %s" % ("已嵌入 %s…" % PUBLIC_KEY_B64[:8] if embedded else "未嵌入（开发版）"))

    if needs_public_key and not embedded:
        print("\n✗ 用户端没有嵌入公钥，这个产物无法通过授权校验")
        return 1

    if needs_engine:
        from engine.slots import make_gap_counter, parse_slot
        gap = make_gap_counter(["08:10-10:10", "10:30-12:30", "14:00-16:00"])
        assert gap(parse_slot("08:10-10:10"), parse_slot("10:30-12:30")) == 0
        print("  引擎        时段运算正常")

    print("\n✓ 自检通过")
    return 0
