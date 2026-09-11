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


def test_管理端生成私钥的完整流程(app, tmp_path, monkeypatch):
    """点「生成私钥」→ 落盘加密 pem → 显示公钥 → 签发按钮可用。"""
    from apps.admin import main as admin
    from licensing import keys

    stored = tmp_path / "secrets" / "admin_private.pem"
    monkeypatch.setattr(admin, "stored_key_path", lambda: stored)
    monkeypatch.setattr(admin.KeyTab, "_ask_passphrase",
                        lambda self, title, confirm: "口令abc")

    w = admin.MainWindow()
    assert "还没有私钥" in w.key_tab.status.text()
    assert not w.key_tab.unlock_button.isEnabled()
    assert not w.key_tab.backup_button.isEnabled()

    w.key_tab.generate()

    assert stored.exists()
    assert stored.read_bytes().startswith(b"-----BEGIN ENCRYPTED PRIVATE KEY-----")
    assert "已解锁" in w.key_tab.status.text()
    assert w.key_tab.backup_button.isEnabled()
    assert w.issue_tab.issue_button.isEnabled()

    # 界面上显示的公钥必须和私钥真的配对
    shown = w.key_tab.pub_view.toPlainText()
    reloaded = keys.load_private(str(stored), "口令abc")
    assert shown == keys.public_to_b64(reloaded.public_key())


def test_管理端重启后需要解锁_口令错了不放行(app, tmp_path, monkeypatch):
    from apps.admin import main as admin

    stored = tmp_path / "secrets" / "admin_private.pem"
    monkeypatch.setattr(admin, "stored_key_path", lambda: stored)
    monkeypatch.setattr(admin.KeyTab, "_ask_passphrase",
                        lambda self, title, confirm: "对口令")
    first = admin.MainWindow()                   # 必须持引用：临时对象会被 GC，底层控件跟着析构
    first.key_tab.generate()

    w = admin.MainWindow()                       # 模拟重启
    assert "还没解锁" in w.key_tab.status.text()
    assert w.key_tab.unlock_button.isEnabled()
    assert not w.issue_tab.issue_button.isEnabled()

    monkeypatch.setattr(admin.KeyTab, "_ask_passphrase",
                        lambda self, title, confirm: "错口令")
    w.key_tab.unlock()
    assert w.state["key"] is None                # 没放行

    monkeypatch.setattr(admin.KeyTab, "_ask_passphrase",
                        lambda self, title, confirm: "对口令")
    w.key_tab.unlock()
    assert w.state["key"] is not None
    assert w.issue_tab.issue_button.isEnabled()


def test_管理端导入别处生成的私钥(app, tmp_path, monkeypatch):
    from apps.admin import main as admin
    from licensing import keys

    # 另一台机器上生成的私钥
    other = tmp_path / "from_elsewhere.pem"
    key = keys.generate()
    keys.save_private(key, str(other), "老口令")

    stored = tmp_path / "secrets" / "admin_private.pem"
    monkeypatch.setattr(admin, "stored_key_path", lambda: stored)
    monkeypatch.setattr(QtWidgets.QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (str(other), "")))
    monkeypatch.setattr(admin.KeyTab, "_ask_passphrase",
                        lambda self, title, confirm: "老口令")

    w = admin.MainWindow()
    w.key_tab.import_key()

    assert stored.exists()
    assert w.key_tab.pub_view.toPlainText() == keys.public_to_b64(key.public_key())
    # 口令原样保留，不会被改掉
    assert keys.load_private(str(stored), "老口令")


def test_管理端签发前会校验必填项(app, no_modal_dialogs):
    from apps.admin.main import MainWindow
    from licensing import keys
    w = MainWindow()
    w.state["key"] = keys.generate()
    w.on_key_changed()
    w.issue_tab.to_edit.setText("")
    w.issue_tab.issue()
    assert no_modal_dialogs == ["缺信息"]
