"""两端共用的界面零件：配色、状态条、表格填充。"""
from PySide6 import QtCore, QtGui, QtWidgets

ACCENT = "#008C9E"
GOOD = "#0CA30C"
WARN = "#B77400"
CRIT = "#D03B3B"
MONO = "Menlo, Consolas, 'DejaVu Sans Mono', monospace"

STYLESHEET = """
QWidget { font-size: 13px; }
QPushButton {
    padding: 6px 14px; border-radius: 5px;
    border: 1px solid palette(mid); background: palette(button);
}
QPushButton:hover:!disabled { border-color: %(accent)s; }
QPushButton#primary {
    background: %(accent)s; color: white; border-color: %(accent)s; font-weight: 600;
}
QPushButton#primary:disabled { background: palette(mid); border-color: palette(mid); }
QGroupBox {
    border: 1px solid palette(mid); border-radius: 6px;
    margin-top: 10px; padding-top: 10px; font-weight: 600;
}
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
QTableView { gridline-color: palette(midlight); }
QHeaderView::section { padding: 5px; border: none; border-bottom: 1px solid palette(mid); }
""" % {"accent": ACCENT}


class StatusBanner(QtWidgets.QFrame):
    """顶部那条授权状态。颜色即状态，不用读文字就知道行不行。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(12, 8, 12, 8)
        self.dot = QtWidgets.QLabel("●")
        self.text = QtWidgets.QLabel("正在检查授权…")
        self.text.setWordWrap(True)
        row.addWidget(self.dot)
        row.addWidget(self.text, 1)
        self.actions = QtWidgets.QHBoxLayout()
        row.addLayout(self.actions)

    def add_button(self, button):
        self.actions.addWidget(button)

    def set_state(self, ok, message, warn=False):
        color = GOOD if ok and not warn else (WARN if warn else CRIT)
        self.dot.setStyleSheet("color: %s; font-size: 15px;" % color)
        self.text.setText(message)
        self.setStyleSheet("QFrame { border: 1px solid %s; border-radius: 6px; }" % color)


class FindingsModel(QtCore.QAbstractTableModel):
    """违规清单表格。级别列用颜色区分硬约束和软约束。"""
    COLUMNS = ["级别", "问题", "位置", "明细"]

    def __init__(self, findings=()):
        super().__init__()
        self.rows = list(findings)

    def set(self, findings):
        self.beginResetModel()
        self.rows = list(findings)
        self.endResetModel()

    def rowCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else len(self.COLUMNS)

    def headerData(self, section, orientation, role=QtCore.Qt.DisplayRole):
        if role == QtCore.Qt.DisplayRole and orientation == QtCore.Qt.Horizontal:
            return self.COLUMNS[section]
        return None

    def data(self, index, role=QtCore.Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        value = getattr(row, self.COLUMNS[index.column()])
        if role == QtCore.Qt.DisplayRole:
            return value
        if role == QtCore.Qt.ForegroundRole and index.column() == 0:
            return QtGui.QColor(CRIT if str(row.级别).startswith("H") else WARN)
        if role == QtCore.Qt.FontRole and index.column() == 0:
            font = QtGui.QFont()
            font.setBold(True)
            return font
        return None


def mono_label(text=""):
    label = QtWidgets.QLabel(text)
    label.setStyleSheet("font-family: %s;" % MONO)
    label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
    return label


def picker(parent, placeholder, on_browse):
    """一行：只读输入框 + 浏览按钮。返回 (行部件, 输入框)。"""
    box = QtWidgets.QWidget(parent)
    row = QtWidgets.QHBoxLayout(box)
    row.setContentsMargins(0, 0, 0, 0)
    edit = QtWidgets.QLineEdit()
    edit.setPlaceholderText(placeholder)
    button = QtWidgets.QPushButton("浏览…")
    button.clicked.connect(on_browse)
    row.addWidget(edit, 1)
    row.addWidget(button)
    return box, edit
