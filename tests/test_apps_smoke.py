"""两端界面的冒烟测试 —— 在打包之前就发现"窗口根本起不来"。

用 offscreen 平台跑，不需要显示器。所有模态对话框都被替换成假的：
真的弹出来会把 CI 卡到超时。
"""
import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

QtWidgets = pytest.importorskip("PySide6.QtWidgets")


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture(autouse=True)
def no_modal_dialogs(monkeypatch):
    """把会阻塞的弹窗全部换掉，并记录它们被调用过。"""
    calls = []
    for name in ("warning", "information", "critical", "question"):
        monkeypatch.setattr(QtWidgets.QMessageBox, name,
                            lambda *a, **k: calls.append(a[1] if len(a) > 1 else ""),
                            raising=False)
    monkeypatch.setattr(QtWidgets.QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: ("", "")))
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: ("", "")))
    monkeypatch.setattr(QtWidgets.QFileDialog, "getExistingDirectory",
                        staticmethod(lambda *a, **k: ""))
    return calls


def test_用户端能起来(app):
    from apps.user.main import MainWindow
    w = MainWindow()
    assert w.windowTitle()
    # 开发版没嵌公钥，功能区必须是禁用的
    assert not w.body.isEnabled()


def test_用户端选了不存在的文件会被拦住(app, tmp_path, no_modal_dialogs):
    from apps.user.main import MainWindow
    w = MainWindow()
    w.schedule_edit.setText(str(tmp_path / "nope.xlsx"))
    w.start_check()
    assert no_modal_dialogs == ["缺文件"]
    assert w.worker is None                  # 没有进后台线程


def test_管理端能起来_且没私钥时不能签发(app):
    from apps.admin.main import MainWindow
    w = MainWindow()
    assert w.windowTitle()
    assert not w.issue_tab.issue_button.isEnabled()


def test_管理端载入私钥后可以签发(app):
    from apps.admin.main import MainWindow
    from licensing import keys
    w = MainWindow()
    w.state["key"] = keys.generate()
    w.on_key_changed()
    assert w.issue_tab.issue_button.isEnabled()


def test_管理端签发前会校验必填项(app, no_modal_dialogs):
    from apps.admin.main import MainWindow
    from licensing import keys
    w = MainWindow()
    w.state["key"] = keys.generate()
    w.on_key_changed()
    w.issue_tab.to_edit.setText("")
    w.issue_tab.issue()
    assert no_modal_dialogs == ["缺信息"]
