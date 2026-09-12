"""防回归：Windows 控制台默认 cp1252，中文一 print 就崩。

用 PYTHONIOENCODING=cp1252 在任何平台上都能复现同一个错误，所以这几条
在 Linux 的 CI 上就能把问题挡住，不用等到 Windows 那个 job 才发现。
"""
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 桌面端与授权入口已归档到 legacy/（见 legacy/README.md），这里只覆盖在用的命令行入口。
ENTRY_POINTS = [
    (["tools/health_check.py", "--help"], 0),
    (["tools/schedule.py", "--help"], 0),
    (["tools/geocode_centers.py", "--help"], 0),
    (["tools/travel_matrix.py", "--help"], 0),
]


@pytest.mark.parametrize("argv,expected", ENTRY_POINTS,
                         ids=[a[0].split("/")[-1] + ":" + a[1] for a, _ in ENTRY_POINTS])
def test_中文输出在cp1252控制台下不崩(argv, expected, tmp_path):
    env = dict(os.environ, PYTHONIOENCODING="cp1252", QT_QPA_PLATFORM="offscreen")
    # 父进程必须显式按 UTF-8 解码：Windows 上 text=True 默认走 cp1252，
    # 子进程输出的 UTF-8 会在读取线程里解码失败，stdout 直接变成 None
    result = subprocess.run([sys.executable] + argv, cwd=ROOT, env=env,
                            capture_output=True, encoding="utf-8", errors="replace",
                            timeout=120)
    combined = result.stdout + result.stderr
    assert "UnicodeEncodeError" not in combined, combined[-800:]
    assert result.returncode == expected, combined[-800:]


def test_缺了console模块也不该崩(tmp_path):
    """console.py 只是 6 行标准库，不该因为它缺失就让整个工具跑不起来。

    用 runpy 跑真实脚本（__file__ 才是对的），事先把 console 标成不可导入，
    各入口应当退回内置实现继续跑，而不是 ModuleNotFoundError。
    """
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import sys, runpy\n"
        "sys.modules['console'] = None\n"        # 让 import console 抛 ImportError
        "sys.argv = ['health_check.py', '--help']\n"
        "runpy.run_path(%r, run_name='__main__')\n"
        % os.path.join(ROOT, "tools", "health_check.py"),
        encoding="utf-8")
    env = dict(os.environ, PYTHONIOENCODING="cp1252")
    result = subprocess.run([sys.executable, str(probe)], cwd=ROOT, env=env,
                            capture_output=True, encoding="utf-8",
                            errors="replace", timeout=120)
    combined = result.stdout + result.stderr
    assert "ModuleNotFoundError" not in combined, combined[-600:]
    assert "UnicodeEncodeError" not in combined, combined[-600:]
    assert "体检一份排班" in combined              # 帮助文本正常打出来了
