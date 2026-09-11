"""防回归：Windows 控制台默认 cp1252，中文一 print 就崩。

用 PYTHONIOENCODING=cp1252 在任何平台上都能复现同一个错误，所以这几条
在 Linux 的 CI 上就能把问题挡住，不用等到 Windows 那个 job 才发现。
"""
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ENTRY_POINTS = [
    (["tools/embed_pubkey.py", "--allow-missing"], 0),
    (["tools/admin_license.py", "--help"], 0),
    (["tools/health_check.py", "--help"], 0),
    (["apps/admin/main.py", "--selftest"], 0),
    (["apps/user/main.py", "--selftest"], 0),
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
