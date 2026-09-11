#!/usr/bin/env python3
"""排班助手 · 管理端

这一端持有私钥，能签发许可。私钥用口令加密存盘，程序不会把它写到别处。
构建产物里没有任何密钥——密钥由管理员在自己机器上生成、自己保管。
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

from PySide6 import QtCore, QtWidgets

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from apps.common.ui import MONO, STYLESHEET, StatusBanner, mono_label, picker   # noqa: E402
from licensing import keys, license as lic   # noqa: E402
from licensing.fingerprint import machine_fingerprint   # noqa: E402
from licensing.gate import app_data_dir   # noqa: E402

APP_NAME = "排班助手 · 管理端"
ALL_FEATURES = [("health_check", "排班体检"), ("solver", "自动排班"),
                ("board", "看板视图"), ("export", "导出")]


def ledger_path():
    return app_data_dir() / "admin_ledger.json"


def read_ledger():
    try:
        with open(ledger_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return []


def append_ledger(entry):
    rows = read_ledger()
    rows.insert(0, entry)
    ledger_path().parent.mkdir(parents=True, exist_ok=True)
    with open(ledger_path(), "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)


class KeyTab(QtWidgets.QWidget):
    """生成密钥对，并给出要嵌进用户端的那串公钥。"""
    changed = QtCore.Signal()

    def __init__(self, state):
        super().__init__()
        self.state = state
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(12)

        warn = QtWidgets.QLabel(
            "私钥一旦泄露，任何人都能签发许可；一旦丢失，已发出的许可仍有效，"
            "但再也签不出新的。请离线备份，且不要放进代码仓库。")
        warn.setWordWrap(True)
        warn.setStyleSheet("color: #B77400;")
        layout.addWidget(warn)

        box = QtWidgets.QGroupBox("密钥文件")
        grid = QtWidgets.QGridLayout(box)
        grid.setColumnStretch(1, 1)
        row, self.dir_edit = picker(self, "存放密钥的文件夹", self.pick_dir)
        self.dir_edit.setText(str(app_data_dir() / "secrets"))
        grid.addWidget(QtWidgets.QLabel("目录"), 0, 0)
        grid.addWidget(row, 0, 1, 1, 2)

        generate = QtWidgets.QPushButton("生成密钥对")
        generate.setObjectName("primary")
        generate.clicked.connect(self.generate)
        grid.addWidget(generate, 1, 1)
        load = QtWidgets.QPushButton("载入已有私钥")
        load.clicked.connect(self.load_existing)
        grid.addWidget(load, 1, 2)
        layout.addWidget(box)

        box = QtWidgets.QGroupBox("嵌进用户端的公钥（构建时用）")
        inner = QtWidgets.QVBoxLayout(box)
        self.pub_view = QtWidgets.QPlainTextEdit()
        self.pub_view.setReadOnly(True)
        self.pub_view.setFixedHeight(56)
        self.pub_view.setStyleSheet("font-family: %s;" % MONO)
        self.pub_view.setPlaceholderText("生成或载入密钥后显示")
        inner.addWidget(self.pub_view)
        hint = QtWidgets.QLabel(
            "把这串填进 GitHub 仓库的 Secret「LICENSE_PUBLIC_KEY_B64」，"
            "CI 构建用户端时会自动写进程序。公钥可以公开，私钥绝对不行。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: palette(mid);")
        inner.addWidget(hint)
        copy = QtWidgets.QPushButton("复制公钥")
        copy.clicked.connect(lambda: QtWidgets.QApplication.clipboard().setText(
            self.pub_view.toPlainText()))
        inner.addWidget(copy, 0, QtCore.Qt.AlignLeft)
        layout.addWidget(box)
        layout.addStretch(1)

    def pick_dir(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "选择密钥目录")
        if path:
            self.dir_edit.setText(path)

    def _ask_passphrase(self, confirm):
        text, ok = QtWidgets.QInputDialog.getText(
            self, "私钥口令", "输入口令：", QtWidgets.QLineEdit.Password)
        if not ok or not text:
            return None
        if confirm:
            again, ok = QtWidgets.QInputDialog.getText(
                self, "私钥口令", "再输一次：", QtWidgets.QLineEdit.Password)
            if not ok or again != text:
                QtWidgets.QMessageBox.warning(self, "口令不一致", "两次输入不一样，没有生成。")
                return None
        return text

    def generate(self):
        directory = self.dir_edit.text().strip()
        if not directory:
            return
        priv = os.path.join(directory, "admin_private.pem")
        if os.path.exists(priv):
            answer = QtWidgets.QMessageBox.warning(
                self, "已存在私钥",
                "覆盖会让所有已签发的许可立即作废。确定要覆盖吗？",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No)
            if answer != QtWidgets.QMessageBox.Yes:
                return
        passphrase = self._ask_passphrase(confirm=True)
        if not passphrase:
            return

        os.makedirs(directory, exist_ok=True)
        key = keys.generate()
        keys.save_private(key, priv, passphrase)
        keys.save_public(key.public_key(), os.path.join(directory, "admin_public.pem"))
        self.state["key"] = key
        self.state["passphrase"] = passphrase
        self.pub_view.setPlainText(keys.public_to_b64(key.public_key()))
        self.changed.emit()
        QtWidgets.QMessageBox.information(
            self, "已生成", "私钥：%s\n公钥：%s" % (priv, os.path.join(directory, "admin_public.pem")))

    def load_existing(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "选择私钥", self.dir_edit.text(), "PEM (*.pem);;所有文件 (*)")
        if not path:
            return
        passphrase = self._ask_passphrase(confirm=False)
        if not passphrase:
            return
        try:
            key = keys.load_private(path, passphrase)
        except (ValueError, TypeError):
            QtWidgets.QMessageBox.warning(self, "打不开", "口令不对，或文件损坏。")
            return
        self.state["key"] = key
        self.state["passphrase"] = passphrase
        self.pub_view.setPlainText(keys.public_to_b64(key.public_key()))
        self.changed.emit()


class IssueTab(QtWidgets.QWidget):
    """签发一张许可。"""
    issued = QtCore.Signal()

    def __init__(self, state):
        super().__init__()
        self.state = state
        layout = QtWidgets.QVBoxLayout(self)

        box = QtWidgets.QGroupBox("许可内容")
        form = QtWidgets.QFormLayout(box)
        self.to_edit = QtWidgets.QLineEdit()
        self.to_edit.setPlaceholderText("发给谁，例如：福田分区排课组")
        form.addRow("客户 / 团队", self.to_edit)

        self.days_spin = QtWidgets.QSpinBox()
        self.days_spin.setRange(1, 3650)
        self.days_spin.setValue(365)
        self.days_spin.setSuffix(" 天")
        form.addRow("有效期", self.days_spin)

        self.seats_spin = QtWidgets.QSpinBox()
        self.seats_spin.setRange(1, 999)
        form.addRow("席位数", self.seats_spin)

        self.machines_edit = QtWidgets.QLineEdit()
        self.machines_edit.setPlaceholderText(
            "机器指纹，多个用逗号隔开；留空 = 不绑定设备，任意机器可用")
        form.addRow("绑定设备", self.machines_edit)

        features = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(features)
        row.setContentsMargins(0, 0, 0, 0)
        self.feature_boxes = {}
        for code, label in ALL_FEATURES:
            cb = QtWidgets.QCheckBox(label)
            cb.setChecked(True)
            self.feature_boxes[code] = cb
            row.addWidget(cb)
        row.addStretch(1)
        form.addRow("功能档位", features)

        self.notes_edit = QtWidgets.QLineEdit()
        form.addRow("备注", self.notes_edit)
        layout.addWidget(box)

        self.issue_button = QtWidgets.QPushButton("签发并保存…")
        self.issue_button.setObjectName("primary")
        self.issue_button.clicked.connect(self.issue)
        layout.addWidget(self.issue_button, 0, QtCore.Qt.AlignLeft)

        self.preview = QtWidgets.QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setStyleSheet("font-family: %s;" % MONO)
        self.preview.setPlaceholderText("签发后这里显示许可内容")
        layout.addWidget(self.preview, 1)
        self.sync()

    def sync(self):
        has_key = self.state.get("key") is not None
        self.issue_button.setEnabled(has_key)
        self.issue_button.setToolTip("" if has_key else "请先在「密钥」页生成或载入私钥")

    def issue(self):
        key = self.state.get("key")
        if key is None:
            return
        if not self.to_edit.text().strip():
            QtWidgets.QMessageBox.warning(self, "缺信息", "请填「客户 / 团队」。")
            return
        features = [c for c, cb in self.feature_boxes.items() if cb.isChecked()]
        if not features:
            QtWidgets.QMessageBox.warning(self, "缺信息", "至少要勾一个功能档位。")
            return

        days = self.days_spin.value()
        expires = (datetime.now(timezone.utc) + timedelta(days=days)
                   ).replace(microsecond=0).isoformat()
        machines = [m.strip() for m in self.machines_edit.text().split(",") if m.strip()]
        lic_id = "LIC-%s" % datetime.now().strftime("%Y%m%d-%H%M%S")

        document = lic.issue(
            key, lic_id=lic_id, issued_to=self.to_edit.text().strip(),
            expires_at=expires, seats=self.seats_spin.value(), machines=machines,
            features=features, notes=self.notes_edit.text().strip())

        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "保存许可文件", "%s.lic" % lic_id, "许可文件 (*.lic)")
        if not path:
            return
        lic.dump(document, path)
        append_ledger({"lic_id": lic_id, "issued_to": document["payload"]["issued_to"],
                       "issued_at": document["payload"]["issued_at"],
                       "expires_at": expires, "seats": self.seats_spin.value(),
                       "machines": machines, "features": features, "file": path})
        self.preview.setPlainText(json.dumps(document["payload"], ensure_ascii=False, indent=2))
        self.issued.emit()
        QtWidgets.QMessageBox.information(
            self, "已签发", "%s\n到期 %s（%d 天）\n\n把这个文件发给用户，"
            "对方在用户端点「导入许可」即可。" % (path, expires[:10], days))


class LedgerTab(QtWidgets.QWidget):
    """已签发台账 —— 谁、什么时候、到期、绑了哪台机器。"""

    HEADERS = ["许可号", "客户 / 团队", "签发", "到期", "席位", "设备", "功能"]

    def __init__(self):
        super().__init__()
        layout = QtWidgets.QVBoxLayout(self)
        self.table = QtWidgets.QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)

        refresh = QtWidgets.QPushButton("刷新")
        refresh.clicked.connect(self.reload)
        layout.addWidget(refresh, 0, QtCore.Qt.AlignLeft)
        self.reload()

    def reload(self):
        rows = read_ledger()
        self.table.setRowCount(len(rows))
        for r, entry in enumerate(rows):
            values = [entry.get("lic_id", ""), entry.get("issued_to", ""),
                      entry.get("issued_at", "")[:10], entry.get("expires_at", "")[:10],
                      str(entry.get("seats", "")),
                      "、".join(entry.get("machines") or []) or "不绑定",
                      "、".join(entry.get("features") or [])]
            for c, value in enumerate(values):
                self.table.setItem(r, c, QtWidgets.QTableWidgetItem(value))
        self.table.resizeColumnsToContents()


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(880, 640)
        self.state = {"key": None, "passphrase": None}

        root = QtWidgets.QWidget()
        self.setCentralWidget(root)
        layout = QtWidgets.QVBoxLayout(root)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        self.banner = StatusBanner()
        layout.addWidget(self.banner)

        self.key_tab = KeyTab(self.state)
        self.issue_tab = IssueTab(self.state)
        self.ledger_tab = LedgerTab()
        tabs = QtWidgets.QTabWidget()
        tabs.addTab(self.key_tab, "密钥")
        tabs.addTab(self.issue_tab, "签发许可")
        tabs.addTab(self.ledger_tab, "台账")
        layout.addWidget(tabs, 1)

        self.key_tab.changed.connect(self.on_key_changed)
        self.issue_tab.issued.connect(self.ledger_tab.reload)
        self.statusBar().addPermanentWidget(
            mono_label("本机指纹 " + machine_fingerprint()))
        self.on_key_changed()

    def on_key_changed(self):
        self.issue_tab.sync()
        if self.state.get("key") is None:
            self.banner.set_state(False, "还没有私钥。先到「密钥」页生成一对，或载入已有私钥。")
        else:
            self.banner.set_state(True, "私钥已载入，可以签发许可。私钥只在内存中，退出即释放。")


def main():
    from console import force_utf8
    force_utf8()

    if "--selftest" in sys.argv:
        from apps.common.selftest import run as selftest
        sys.exit(selftest("排班助手 · 管理端", needs_public_key=False, needs_engine=False))

    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyleSheet(STYLESHEET)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
