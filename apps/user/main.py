#!/usr/bin/env python3
"""排班助手 · 用户端

这一端只有公钥：能验许可，不能签许可。没有有效许可时，功能区整体禁用。
"""
import csv
import os
import sys
from dataclasses import asdict

from PySide6 import QtCore, QtWidgets

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from apps.common.ui import FindingsModel, MONO, STYLESHEET, StatusBanner, mono_label, picker  # noqa: E402
from engine import load_config, run   # noqa: E402
from licensing import LicenseError, machine_fingerprint   # noqa: E402
from licensing import gate   # noqa: E402

APP_NAME = "排班助手"


class CheckWorker(QtCore.QThread):
    """体检放后台线程跑——几百行表也要几秒，不能卡住界面。"""
    done = QtCore.Signal(object)
    failed = QtCore.Signal(str)

    def __init__(self, schedule, config, sheet):
        super().__init__()
        self.schedule, self.config, self.sheet = schedule, config, sheet

    def run(self):
        try:
            cfg = load_config(self.config)
            self.done.emit(run(self.schedule, cfg, self.sheet or None))
        except Exception as e:                       # noqa: BLE001 — 要把原因显示给用户
            self.failed.emit("%s: %s" % (type(e).__name__, e))


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1060, 720)
        self.report = None
        self.worker = None

        root = QtWidgets.QWidget()
        self.setCentralWidget(root)
        layout = QtWidgets.QVBoxLayout(root)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        self.banner = StatusBanner()
        install = QtWidgets.QPushButton("导入许可…")
        install.clicked.connect(self.install_license)
        self.banner.add_button(install)
        layout.addWidget(self.banner)

        self.body = QtWidgets.QWidget()
        layout.addWidget(self.body, 1)
        body = QtWidgets.QVBoxLayout(self.body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(12)
        body.addWidget(self._inputs())

        split = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        self.summary = QtWidgets.QPlainTextEdit()
        self.summary.setReadOnly(True)
        self.summary.setStyleSheet("font-family: %s;" % MONO)
        self.summary.setPlaceholderText("选好文件，点「开始体检」。")
        split.addWidget(self.summary)

        self.model = FindingsModel()
        self.table = QtWidgets.QTableView()
        self.table.setModel(self.model)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        split.addWidget(self.table)
        split.setSizes([300, 340])
        body.addWidget(split, 1)

        self.statusBar().addPermanentWidget(
            mono_label("本机指纹 " + machine_fingerprint()))
        self.refresh_license()

    def _inputs(self):
        box = QtWidgets.QGroupBox("排班体检")
        form = QtWidgets.QGridLayout(box)
        form.setColumnStretch(1, 1)

        row, self.schedule_edit = picker(self, "排班明细 .xlsx", self.pick_schedule)
        form.addWidget(QtWidgets.QLabel("排班明细"), 0, 0)
        form.addWidget(row, 0, 1, 1, 3)

        row, self.config_edit = picker(self, "规则配置 .yaml", self.pick_config)
        self.config_edit.setText(self._default_config())
        form.addWidget(QtWidgets.QLabel("规则配置"), 1, 0)
        form.addWidget(row, 1, 1, 1, 3)

        self.sheet_edit = QtWidgets.QLineEdit()
        self.sheet_edit.setPlaceholderText("留空 = 第一个工作表")
        form.addWidget(QtWidgets.QLabel("工作表"), 2, 0)
        form.addWidget(self.sheet_edit, 2, 1)

        self.run_button = QtWidgets.QPushButton("开始体检")
        self.run_button.setObjectName("primary")
        self.run_button.clicked.connect(self.start_check)
        form.addWidget(self.run_button, 2, 2)

        self.export_button = QtWidgets.QPushButton("导出违规清单…")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self.export_findings)
        form.addWidget(self.export_button, 2, 3)
        return box

    @staticmethod
    def _default_config():
        here = os.path.dirname(os.path.abspath(__file__))
        base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(here)))
        guess = os.path.join(base, "config", "rules.example.yaml")
        return guess if os.path.exists(guess) else ""

    # ── 授权 ──────────────────────────────────────────────────────
    def refresh_license(self):
        try:
            payload = gate.check()
        except LicenseError as e:
            self.banner.set_state(False, str(e))
            self.body.setEnabled(False)
            return
        from licensing.license import days_left
        left = days_left(payload)
        self.banner.set_state(True, gate.status_line(payload), warn=left <= 30)
        self.body.setEnabled(True)

    def install_license(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "选择管理员发来的许可文件", "", "许可文件 (*.lic);;所有文件 (*)")
        if not path:
            return
        try:
            gate.install(path)
        except LicenseError as e:
            QtWidgets.QMessageBox.warning(self, "许可不可用", str(e))
        else:
            QtWidgets.QMessageBox.information(self, "已导入", "许可已生效。")
        self.refresh_license()

    # ── 体检 ──────────────────────────────────────────────────────
    def pick_schedule(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "选择排班明细", "", "Excel (*.xlsx *.xlsm);;所有文件 (*)")
        if path:
            self.schedule_edit.setText(path)

    def pick_config(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "选择规则配置", "", "YAML (*.yaml *.yml);;所有文件 (*)")
        if path:
            self.config_edit.setText(path)

    def start_check(self):
        schedule, config = self.schedule_edit.text().strip(), self.config_edit.text().strip()
        if not os.path.exists(schedule):
            QtWidgets.QMessageBox.warning(self, "缺文件", "请先选择排班明细 .xlsx")
            return
        if not os.path.exists(config):
            QtWidgets.QMessageBox.warning(self, "缺文件", "请先选择规则配置 .yaml")
            return
        try:
            gate.check(required_feature="health_check")
        except LicenseError as e:
            QtWidgets.QMessageBox.warning(self, "授权不可用", str(e))
            self.refresh_license()
            return

        self.run_button.setEnabled(False)
        self.run_button.setText("体检中…")
        self.summary.setPlainText("正在读表并检查，请稍候…")
        self.worker = CheckWorker(schedule, config, self.sheet_edit.text().strip())
        self.worker.done.connect(self.on_done)
        self.worker.failed.connect(self.on_failed)
        self.worker.finished.connect(self.on_finished)
        self.worker.start()

    def on_finished(self):
        self.run_button.setEnabled(True)
        self.run_button.setText("开始体检")

    def on_failed(self, message):
        self.summary.setPlainText("没跑起来：\n\n" + message)
        self.model.set([])
        self.export_button.setEnabled(False)

    def on_done(self, report):
        from tools.health_check import render
        self.report = report
        self.summary.setPlainText(
            render(report, os.path.basename(self.schedule_edit.text())))
        self.model.set(report.findings)
        self.table.resizeColumnsToContents()
        self.export_button.setEnabled(bool(report.findings))
        self.statusBar().showMessage(
            "%s · 违规 %d 条" % ("可行" if report.可行 else "存在硬约束违规",
                                len(report.findings)), 8000)

    def export_findings(self):
        if not self.report:
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "导出违规清单", "违规清单.csv", "CSV (*.csv)")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=["级别", "问题", "位置", "明细"])
            writer.writeheader()
            writer.writerows(asdict(x) for x in self.report.findings)
        self.statusBar().showMessage("已导出 %d 条 → %s" % (len(self.report.findings), path), 8000)


def main():
    if "--selftest" in sys.argv:
        from apps.common.selftest import run as selftest
        sys.exit(selftest("排班助手 · 用户端", needs_public_key=True))

    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyleSheet(STYLESHEET)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
