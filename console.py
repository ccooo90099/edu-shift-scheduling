"""把标准输出强制成 UTF-8。

Windows 控制台默认是 cp1252/GBK，中文一 print 就 UnicodeEncodeError —— 崩的不只是
CI，用户在 Windows 上跑命令行也一样。所以修在代码里，不是修在 workflow 的环境变量里。

每个入口的 main() 第一行调用它，要赶在 argparse 之前（帮助文本也是中文）。
"""
import sys


def force_utf8():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            # 已被重定向成不支持 reconfigure 的对象时忽略：
            # 编码问题不该反过来把程序搞崩
            pass
