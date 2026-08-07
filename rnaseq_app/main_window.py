"""
转录组分析软件 - 主界面

三大分析模块:
  [1. De Novo 组装]  [2. 序列比对]  [3. 差异表达分析]
        ┃                    ┃                 ┃
        ┃                (开发中占位)     (开发中占位)
        ▼
┌──────────┬─────────────────────┬──────────┐
│          │                     │          │
│  步骤    │     主内容区         │  参数    │
│  导航    │   (QStackedWidget)   │  面板    │
│  列表    │                     │          │
│          │                     │          │
├──────────┴─────────────────────┴──────────┤
│              日志输出面板                    │
├───────────────────────────────────────────┤
│  [上一步] [运行选中] [运行全部] [停止]       │
└───────────────────────────────────────────┘
"""

import os
import sys
import subprocess
from typing import List, Optional

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QPushButton, QLabel, QFrame, QListWidget, QListWidgetItem,
    QStackedWidget, QProgressBar, QMessageBox, QFileDialog,
    QTabWidget, QLineEdit, QSpinBox, QDoubleSpinBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QCheckBox, QGroupBox,
    QFormLayout, QAbstractItemView,
    QPlainTextEdit, QAction, QScrollArea,
    QMenu,
)
from PyQt5.QtCore import Qt, QThread, pyqtSlot, pyqtSignal
from PyQt5.QtGui import QColor, QTextCursor

from .config import ConfigManager
from .env_manager import (
    CondaEnvManager, PACKAGES,
    get_local_conda_dir,
)
from .steps import PIPELINE_STEPS, StepStatus, AnalysisContext, SampleInfo
from .pipeline import AnalysisWorker
from . import __version__


# ============================================================
# 资源路径工具 (兼容 PyInstaller 打包)
# ============================================================

def resource_path(relative_path: str) -> str:
    """获取资源文件的绝对路径，兼容开发模式和 PyInstaller 打包模式"""
    try:
        base = sys._MEIPASS  # PyInstaller 临时目录
    except AttributeError:
        base = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    return os.path.join(base, relative_path)


def get_app_icon():
    """获取应用图标路径"""
    for ext in [".png", ".svg"]:
        icon_path = resource_path(f"rnaseq_app/resources/icon{ext}")
        if os.path.isfile(icon_path):
            return icon_path
    return ""


# ============================================================
# 配色方案
# ============================================================

COLORS = {
    "bg": "#f5f6fa",
    "sidebar_bg": "#2c3e50",
    "sidebar_text": "#ecf0f1",
    "sidebar_active": "#3498db",
    "success": "#27ae60",
    "error": "#e74c3c",
    "warning": "#f39c12",
    "running": "#3498db",
    "pending": "#95a5a6",
    "skipped": "#bdc3c7",
    "border": "#dcdde1",
    "primary_btn": "#3498db",
    "primary_btn_hover": "#2980b9",
    "danger_btn": "#e74c3c",
    "card_bg": "#ffffff",
}


def group_style() -> str:
    """分组卡片统一样式（供多个页面共用）"""
    return f"""
        QGroupBox {{
            font-weight: bold;
            border: 1px solid {COLORS['border']};
            border-radius: 8px;
            margin-top: 12px;
            padding-top: 20px;
            background-color: {COLORS['card_bg']};
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 16px;
            padding: 0 8px;
        }}
    """


# ============================================================
# 后台任务线程
# ============================================================

class EnvTaskWorker(QThread):
    """
    在后台线程执行 conda 任务，避免冻结 GUI。
    任务函数 fn 在子线程运行，完成后通过 done 信号回传 (成功, 消息)。
    """

    done = pyqtSignal(bool, str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self):
        try:
            result = self._fn()
            if isinstance(result, tuple) and len(result) >= 2:
                self.done.emit(bool(result[0]), str(result[1]))
            else:
                self.done.emit(bool(result), "")
        except Exception as e:
            self.done.emit(False, f"执行出错: {e}")


class TerminalWorker(QThread):
    """
    基于 pty 伪终端的实时终端工作线程。
    - 实时流式输出（不用等命令结束）
    - 支持向运行中的进程发送输入（conda 确认 y/n 等交互）
    - 结束通过 terminated(bool, msg) 回传
    """

    output = pyqtSignal(str)            # 实时输出文本
    terminated = pyqtSignal(bool, str)  # (成功, 退出消息)

    def __init__(self, bash_exe: str, cmd: str, parent=None):
        super().__init__(parent)
        self._bash_exe = bash_exe
        self._cmd = cmd
        self._master = None
        self._proc = None
        self._stop = False

    def send_input(self, text: str):
        """向运行中的进程发送输入（回车自动补）"""
        if self._master is not None and self._proc and self._proc.poll() is None:
            try:
                os.write(self._master, (text + "\n").encode())
                return True
            except OSError:
                pass
        return False

    def request_stop(self):
        self._stop = True

    def run(self):
        try:
            import pty
            import select
        except ImportError:
            # 无 pty 平台（如 Windows 开发机）：退化为一次性捕获
            self._run_plain()
            return

        try:
            master, slave = pty.openpty()
            self._master = master
            self._proc = subprocess.Popen(
                [self._bash_exe, "-c", self._cmd],
                stdin=slave, stdout=slave, stderr=slave,
                close_fds=True,
            )
            os.close(slave)

            buf = b""
            while True:
                if self._stop:
                    self._proc.terminate()
                    break
                r, _, _ = select.select([master], [], [], 0.3)
                if r:
                    try:
                        data = os.read(master, 4096)
                    except OSError:
                        break
                    if not data:
                        break
                    buf += data
                    # 按完整行发射，保证逐行实时刷新
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        self.output.emit(line.decode(errors="replace"))
                if self._proc.poll() is not None:
                    # 读尽剩余输出
                    try:
                        while True:
                            r, _, _ = select.select([master], [], [], 0)
                            if not r:
                                break
                            data = os.read(master, 4096)
                            if not data:
                                break
                            buf += data
                    except OSError:
                        pass
                    break

            if buf:
                self.output.emit(buf.decode(errors="replace"))
            os.close(master)
            self._master = None
            rc = self._proc.returncode
            self.terminated.emit(rc == 0, f"exit={rc}")
        except Exception as e:
            self.terminated.emit(False, f"终端错误: {e}")

    def _run_plain(self):
        """无 pty 平台的退化实现：一次性捕获输出"""
        try:
            self._proc = subprocess.Popen(
                [self._bash_exe, "-c", self._cmd],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True,
            )
            out, _ = self._proc.communicate()
            if out:
                self.output.emit(out)
            rc = self._proc.returncode
            self.terminated.emit(rc == 0, f"exit={rc}")
        except Exception as e:
            self.terminated.emit(False, f"终端错误: {e}")


class TermInput(QLineEdit):
    """带命令历史 + Tab 补全请求的终端输入框"""

    tab_pressed = pyqtSignal(str)  # 携带当前输入文本，由外部完成补全

    def __init__(self, parent=None):
        super().__init__(parent)
        self._history: List[str] = []
        self._idx = -1

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Tab:
            # 发出补全请求（不切换焦点）
            self.tab_pressed.emit(self.text())
            return
        if event.key() == Qt.Key_Up:
            if self._history and self._idx > 0:
                self._idx -= 1
                self.setText(self._history[self._idx])
            elif self._history:
                self._idx = 0
                self.setText(self._history[0])
            return
        if event.key() == Qt.Key_Down:
            if self._idx >= 0:
                self._idx += 1
                if self._idx < len(self._history):
                    self.setText(self._history[self._idx])
                else:
                    self._idx = len(self._history)
                    self.clear()
            return
        super().keyPressEvent(event)

    def commit_command(self, text: str):
        """记录命令到历史"""
        text = text.strip()
        if text:
            self._history.append(text)
            if len(self._history) > 200:  # 限制历史长度
                self._history.pop(0)
        self._idx = len(self._history)
        self.clear()


# conda 常用子命令（用于 Tab 补全）
CONDA_SUBCOMMANDS = [
    "activate", "create", "install", "update", "remove", "uninstall",
    "list", "search", "info", "config", "clean", "env", "run",
    "init", "build", "package", "verify", "compare", "convert",
    "debug", "develop", "help", "inspect", "render",
]


# ============================================================
# 模块导航栏
# ============================================================

class ModuleNavBar(QFrame):
    """顶部三大模块导航栏"""

    module_selected = pyqtSignal(int)

    # 模块定义: (名称, 状态, 说明)
    MODULES = [
        ("1. De Novo 组装", "可用"),
        ("2. 序列比对", "开发中"),
        ("3. 差异表达分析", "开发中"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(52)
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS['sidebar_bg']};
                border: none;
            }}
        """)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(6)

        # 应用名
        app_label = QLabel("🧬 TVAS · 转录组分析")
        app_label.setStyleSheet(f"""
            QLabel {{
                color: {COLORS['sidebar_text']};
                font-size: 15px;
                font-weight: bold;
                padding-right: 16px;
            }}
        """)
        layout.addWidget(app_label)
        layout.addSpacing(8)

        self._buttons: List[QPushButton] = []
        for idx, (name, status) in enumerate(self.MODULES):
            btn = QPushButton(name)
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(f"""
                QPushButton {{
                    color: {COLORS['sidebar_text']};
                    background: transparent;
                    border: none;
                    padding: 8px 18px;
                    border-radius: 6px;
                    font-size: 14px;
                }}
                QPushButton:hover {{
                    background-color: rgba(255,255,255,0.12);
                }}
                QPushButton:checked {{
                    background-color: {COLORS['sidebar_active']};
                    color: white;
                    font-weight: bold;
                }}
            """)
            btn.clicked.connect(lambda checked, i=idx: self._select(i))
            layout.addWidget(btn)
            self._buttons.append(btn)

        layout.addStretch()

        # 版本号
        ver_label = QLabel(f"v{__version__}")
        ver_label.setStyleSheet(f"color: rgba(255,255,255,0.6); font-size: 12px;")
        layout.addWidget(ver_label)

        self._select(0)

    def _select(self, idx: int):
        """选中指定模块"""
        for i, btn in enumerate(self._buttons):
            btn.setChecked(i == idx)
        self.module_selected.emit(idx)


# ============================================================
# 开发中模块占位页
# ============================================================

class ModulePlaceholderPage(QWidget):
    """尚未开发完成的分析模块占位页"""

    def __init__(self, module_name: str, module_desc: str,
                 planned_steps: List[tuple], parent=None):
        """
        module_name: 模块名称
        module_desc: 模块功能说明
        planned_steps: [(步骤名, 说明), ...] 计划支持的分析流程
        """
        super().__init__(parent)
        self.module_name = module_name
        self._setup_ui(module_desc, planned_steps)

    def _setup_ui(self, module_desc: str, planned_steps: List[tuple]):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(20)

        # 标题行
        header = QHBoxLayout()
        title = QLabel(self.module_name)
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #2c3e50;")
        header.addWidget(title)

        badge = QLabel(" 开发中 ")
        badge.setStyleSheet(f"""
            QLabel {{
                background-color: {COLORS['warning']};
                color: white;
                font-weight: bold;
                font-size: 12px;
                border-radius: 4px;
                padding: 3px 10px;
            }}
        """)
        header.addWidget(badge)
        header.addStretch()
        layout.addLayout(header)

        # 说明
        desc = QLabel(module_desc)
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #7f8c8d; font-size: 14px;")
        layout.addWidget(desc)

        layout.addSpacing(10)

        # 计划流程
        plan_label = QLabel("📋 本模块计划支持的分析流程：")
        plan_label.setStyleSheet("font-size: 15px; font-weight: bold; color: #34495e;")
        layout.addWidget(plan_label)

        for name, step_desc in planned_steps:
            card = QFrame()
            card.setStyleSheet(f"""
                QFrame {{
                    background-color: {COLORS['card_bg']};
                    border: 1px solid {COLORS['border']};
                    border-radius: 8px;
                }}
            """)
            card_layout = QHBoxLayout(card)
            card_layout.setContentsMargins(16, 10, 16, 10)

            icon = QLabel("⏳")
            icon.setStyleSheet("font-size: 18px;")
            card_layout.addWidget(icon)

            text_col = QVBoxLayout()
            text_col.setSpacing(2)
            step_title = QLabel(name)
            step_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #2c3e50;")
            text_col.addWidget(step_title)
            step_desc_label = QLabel(step_desc)
            step_desc_label.setWordWrap(True)
            step_desc_label.setStyleSheet("color: #95a5a6; font-size: 12px;")
            text_col.addWidget(step_desc_label)
            card_layout.addLayout(text_col, 1)

            layout.addWidget(card)

        layout.addStretch()

        # 底部提示
        tip = QLabel("该模块正在开发中，将在后续版本中开放。当前版本请使用「1. De Novo 组装」模块。")
        tip.setStyleSheet("color: #bdc3c7; font-size: 12px;")
        layout.addWidget(tip)


# ============================================================
# 步骤列表控件
# ============================================================

class StepListWidget(QFrame):
    """左侧步骤导航列表"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(220)
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS['sidebar_bg']};
                border: none;
            }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # 标题
        title = QLabel("  分析流程")
        title.setStyleSheet(f"""
            QLabel {{
                color: {COLORS['sidebar_text']};
                font-size: 16px;
                font-weight: bold;
                padding: 16px 10px 8px 10px;
            }}
        """)
        layout.addWidget(title)

        # 步骤列表
        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet(f"""
            QListWidget {{
                background: transparent;
                border: none;
                outline: none;
                padding: 4px;
            }}
            QListWidget::item {{
                color: {COLORS['sidebar_text']};
                padding: 10px 12px;
                border-radius: 6px;
                margin: 2px 8px;
            }}
            QListWidget::item:selected {{
                background-color: {COLORS['sidebar_active']};
            }}
            QListWidget::item:hover {{
                background-color: rgba(255,255,255,0.1);
            }}
        """)
        layout.addWidget(self.list_widget)

        self._items: List[QListWidgetItem] = []
        self._step_ids: List[str] = []

    def populate(self, steps: List[dict]):
        """填充步骤列表"""
        self.list_widget.clear()
        self._items.clear()
        self._step_ids.clear()

        for i, step in enumerate(steps):
            text = f"  {i+1}. {step['name']}"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, step["id"])
            self.list_widget.addItem(item)
            self._items.append(item)
            self._step_ids.append(step["id"])

    def set_step_status(self, step_id: str, status: str):
        """更新步骤状态图标"""
        icons = {
            StepStatus.PENDING.value: ("○", COLORS["pending"]),
            StepStatus.RUNNING.value: ("◉", COLORS["running"]),
            StepStatus.SUCCESS.value: ("✓", COLORS["success"]),
            StepStatus.FAILED.value: ("✗", COLORS["error"]),
            StepStatus.SKIPPED.value: ("−", COLORS["skipped"]),
        }
        if step_id in self._step_ids:
            idx = self._step_ids.index(step_id)
            if idx < len(self._items):
                icon, color = icons.get(status, ("○", COLORS["pending"]))
                step = PIPELINE_STEPS[idx]
                prefix = f" {icon} "
                self._items[idx].setText(f"{prefix}{idx+1}. {step['name']}")

    def reset_all(self):
        """重置所有步骤状态"""
        for i, step in enumerate(PIPELINE_STEPS):
            self._items[i].setText(f"  ○ {i+1}. {step['name']}")


# ============================================================
# 环境设置页
# ============================================================

class EnvSetupPage(QWidget):
    """环境设置页面"""

    def __init__(self, config: ConfigManager, parent=None):
        super().__init__(parent)
        self.config = config
        self.env_manager: Optional[CondaEnvManager] = None
        self._env_ready = False       # 环境是否就绪（决定按钮可用性）
        self._env_worker = None       # 后台任务线程引用（防 GC）
        self._term_worker = None      # 终端 pty 线程引用
        self._verify_results = []     # 验证结果缓存（后台线程回传）
        self._install_results = []    # 安装结果缓存
        self._setup_ui()

    # ---- 环境任务后台执行与忙碌状态 ----

    def _run_env_task(self, fn, on_done):
        """后台执行 conda 任务，完成后在主线程回调 on_done(ok, msg)"""
        self._env_worker = EnvTaskWorker(fn)
        self._env_worker.done.connect(
            lambda ok, msg: self._on_env_task_done(ok, msg, on_done)
        )
        self._env_worker.start()

    def _on_env_task_done(self, ok: bool, msg: str, on_done):
        self._set_env_busy(False)
        if on_done:
            on_done(ok, msg)
        self._env_worker = None

    def _set_env_busy(self, busy: bool, label: str = ""):
        """
        任务执行期间统一管理：忙碌光标 + 状态栏提示 + 禁用操作按钮，
        避免界面假死、用户误以为卡死。
        """
        if busy:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            win = self.window()
            if isinstance(win, QMainWindow):
                win.statusBar().showMessage(f"⏳ {label}，请稍候...")
            for w in (
                self.install_btn, self.verify_btn, self.more_btn,
                self.custom_install_btn, self.term_input,
                self.uninstall_btn, self.uninstall_all_btn,
                self.retry_btn, self.create_env_btn, self.detect_btn,
            ):
                w.setEnabled(False)
        else:
            QApplication.restoreOverrideCursor()
            win = self.window()
            if isinstance(win, QMainWindow):
                win.statusBar().showMessage("就绪")
            self._refresh_env_buttons()

    def _refresh_env_buttons(self):
        """根据环境就绪状态刷新所有操作按钮"""
        ready = self._env_ready
        for w in (
            self.install_btn, self.verify_btn, self.more_btn,
            self.custom_install_btn, self.uninstall_btn,
            self.uninstall_all_btn, self.retry_btn,
        ):
            w.setEnabled(ready)
        self.term_input.setEnabled(ready)

    def _setup_ui(self):
        # 外层滚动区域（解决窗口小内容被挤压的问题）
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")
        outer.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setSpacing(16)
        layout.setContentsMargins(12, 12, 12, 12)

        # ---- Conda 检测 ----
        group1 = QGroupBox("Conda 环境")
        group1.setStyleSheet(group_style())
        g1_layout = QFormLayout(group1)

        self.conda_path_edit = QLineEdit()
        self.conda_path_edit.setPlaceholderText("自动检测（留空则自动搜索）")
        self.conda_path_edit.setText(self.config.conda_path)
        g1_layout.addRow("Conda 路径:", self.conda_path_edit)

        self.env_name_edit = QLineEdit()
        self.env_name_edit.setText(self.config.conda_env_name)
        g1_layout.addRow("环境名称:", self.env_name_edit)

        self.conda_status_label = QLabel("尚未检测")
        self.conda_status_label.setStyleSheet("color: #888;")
        g1_layout.addRow("状态:", self.conda_status_label)

        btn_layout = QHBoxLayout()
        self.detect_btn = QPushButton("检测 Conda")
        self.detect_btn.clicked.connect(self._detect_conda)
        self.create_env_btn = QPushButton("创建环境")
        self.create_env_btn.clicked.connect(self._create_env)
        self.create_env_btn.setEnabled(False)
        btn_layout.addWidget(self.detect_btn)
        btn_layout.addWidget(self.create_env_btn)
        btn_layout.addStretch()
        g1_layout.addRow("", btn_layout)

        layout.addWidget(group1)

        # ---- 软件包安装 ----
        group2 = QGroupBox("软件包安装（★ 为 De Novo 流程必需）")
        group2.setStyleSheet(group_style())
        g2_layout = QVBoxLayout(group2)

        self.pkg_table = QTableWidget()
        self.pkg_table.setColumnCount(4)
        self.pkg_table.setHorizontalHeaderLabels(["软件包", "已装版本", "类型", "状态"])
        self.pkg_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.pkg_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.pkg_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.pkg_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.pkg_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.pkg_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.pkg_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.pkg_table.verticalHeader().setVisible(False)
        self.pkg_table.setAlternatingRowColors(True)
        self.pkg_table.setMinimumHeight(300)
        self.pkg_table.setToolTip("选中一行可单独重装；双击行也触发重装")
        self._populate_pkg_table()
        g2_layout.addWidget(self.pkg_table)

        # 主操作按钮行（次要操作收纳在「更多操作」菜单中）
        pkg_btn_layout = QHBoxLayout()
        self.install_btn = QPushButton("▶ 安装全部软件包")
        self.install_btn.clicked.connect(self._install_packages)
        self.install_btn.setEnabled(False)
        self.install_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['primary_btn']};
                color: white;
                padding: 10px 26px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 14px;
            }}
            QPushButton:hover {{ background-color: {COLORS['primary_btn_hover']}; }}
            QPushButton:disabled {{ background-color: #bdc3c7; }}
        """)
        self.verify_btn = QPushButton("✓ 验证安装")
        self.verify_btn.clicked.connect(self._verify_packages)
        self.verify_btn.setEnabled(False)
        self.verify_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['success']};
                color: white;
                padding: 10px 20px;
                border-radius: 4px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background-color: #219150; }}
            QPushButton:disabled {{ background-color: #bdc3c7; }}
        """)

        # 「更多操作」下拉菜单（重装/卸载等次要操作）
        self.more_menu = QMenu(self)
        self.retry_btn = QAction("↻ 重装选中软件包", self)
        self.retry_btn.triggered.connect(lambda: self._retry_package())
        self.retry_btn.setToolTip("在表格中选中一行（可多选），点击后仅重装选中的软件包")
        self.retry_btn.setEnabled(False)
        self.more_menu.addAction(self.retry_btn)

        self.uninstall_btn = QAction("✕ 卸载选中软件包", self)
        self.uninstall_btn.triggered.connect(lambda: self._uninstall_package())
        self.uninstall_btn.setToolTip("在表格中选中一行（可多选），点击后仅卸载选中的软件包")
        self.uninstall_btn.setEnabled(False)
        self.more_menu.addAction(self.uninstall_btn)

        self.more_menu.addSeparator()

        self.uninstall_all_btn = QAction("🗑 卸载全部（删除环境重建）", self)
        self.uninstall_all_btn.triggered.connect(self._uninstall_all)
        self.uninstall_all_btn.setToolTip("删除整个分析环境并清空，之后需重新创建环境并安装软件")
        self.uninstall_all_btn.setEnabled(False)
        self.more_menu.addAction(self.uninstall_all_btn)

        self.more_btn = QPushButton("更多操作 ▾")
        self.more_btn.setMenu(self.more_menu)
        self.more_btn.setEnabled(False)
        self.more_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #7f8c8d;
                color: white;
                padding: 10px 16px;
                border-radius: 4px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background-color: #6c7a7a; }}
            QPushButton:disabled {{ background-color: #bdc3c7; }}
        """)

        pkg_btn_layout.addWidget(self.install_btn)
        pkg_btn_layout.addWidget(self.verify_btn)
        pkg_btn_layout.addWidget(self.more_btn)
        pkg_btn_layout.addStretch()
        g2_layout.addLayout(pkg_btn_layout)

        # 双击某行也触发重装
        self.pkg_table.itemDoubleClicked.connect(self._retry_package)

        layout.addWidget(group2)

        # ---- 高级设置（默认隐藏，点击按钮展开） ----
        self.adv_toggle_btn = QPushButton("▸ 高级设置（自定义安装 · 环境终端 · 命令日志）")
        self.adv_toggle_btn.setCheckable(True)
        self.adv_toggle_btn.setChecked(False)
        self.adv_toggle_btn.setCursor(Qt.PointingHandCursor)
        self.adv_toggle_btn.toggled.connect(self._toggle_advanced)
        self.adv_toggle_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #34495e;
                color: white;
                padding: 8px 14px;
                border-radius: 4px;
                font-weight: bold;
                text-align: left;
            }}
            QPushButton:hover {{ background-color: #2c3e50; }}
        """)
        layout.addWidget(self.adv_toggle_btn)

        # 高级设置内容容器（默认隐藏）
        self.adv_container = QWidget()
        self.adv_container.setVisible(False)
        adv_layout = QVBoxLayout(self.adv_container)
        adv_layout.setContentsMargins(0, 8, 0, 0)
        adv_layout.setSpacing(8)

        # 自定义安装
        custom_row = QHBoxLayout()
        custom_label = QLabel("自定义安装:")
        custom_label.setStyleSheet("color: #555;")
        custom_row.addWidget(custom_label)
        self.custom_pkg_edit = QLineEdit()
        self.custom_pkg_edit.setPlaceholderText("输入软件包名，如 salmon / hisat2=2.2.1 / bwa-mem2")
        self.custom_pkg_edit.returnPressed.connect(self._install_custom)
        custom_row.addWidget(self.custom_pkg_edit, 1)
        self.custom_install_btn = QPushButton("安装")
        self.custom_install_btn.clicked.connect(self._install_custom)
        self.custom_install_btn.setEnabled(False)
        custom_row.addWidget(self.custom_install_btn)
        adv_layout.addLayout(custom_row)

        # 环境终端：视觉一体的终端容器（输出区 + 输入行在同一黑底框内）
        term_title = QLabel("环境终端（命令在分析环境中执行，回车运行，上下键翻历史）")
        term_title.setStyleSheet("color: #555; font-weight: bold;")
        adv_layout.addWidget(term_title)

        term_box = QFrame()
        term_box.setStyleSheet("""
            QFrame {
                background-color: #1e1e1e;
                border: 1px solid #333;
                border-radius: 6px;
            }
        """)
        term_box_layout = QVBoxLayout(term_box)
        term_box_layout.setContentsMargins(8, 8, 8, 8)
        term_box_layout.setSpacing(4)

        self.adv_log_view = QPlainTextEdit()
        self.adv_log_view.setReadOnly(True)
        self.adv_log_view.setMinimumHeight(200)
        self.adv_log_view.setPlaceholderText(
            "这是一个内置小终端，直接输入命令操作分析环境，例如：\n"
            "  conda list                            # 查看已安装软件包\n"
            "  conda install -c bioconda trinity=2.15  # 安装 Trinity\n"
            "  Trinity --version                     # 查看版本\n"
            "执行中可继续输入内容发送给命令（如 conda 询问 y/n 时输入 y 回车）"
        )
        self.adv_log_view.setStyleSheet("""
            QPlainTextEdit {
                background-color: transparent;
                color: #d4d4d4;
                font-family: "Consolas", "DejaVu Sans Mono", monospace;
                font-size: 12px;
                border: none;
            }
        """)
        term_box_layout.addWidget(self.adv_log_view)

        term_input_row = QHBoxLayout()
        term_input_row.setSpacing(6)
        prompt = QLabel("$")
        prompt.setStyleSheet(f"color: {COLORS['success']}; font-weight: bold; font-size: 14px;")
        term_input_row.addWidget(prompt)
        self.term_input = TermInput()
        self.term_input.setPlaceholderText("输入命令后按回车执行，Tab 键自动补全...")
        self.term_input.returnPressed.connect(self._on_terminal_enter)
        self.term_input.tab_pressed.connect(self._on_terminal_tab)
        self.term_input.setEnabled(False)
        self.term_input.setStyleSheet("""
            QLineEdit {
                background-color: transparent;
                color: #d4d4d4;
                font-family: "Consolas", "DejaVu Sans Mono", monospace;
                font-size: 12px;
                border: none;
                padding: 2px 0;
            }
        """)
        term_input_row.addWidget(self.term_input, 1)
        term_box_layout.addLayout(term_input_row)

        adv_layout.addWidget(term_box)

        # 日志快捷按钮
        log_row = QHBoxLayout()
        log_row.addStretch()
        self.view_pkg_log_btn = QPushButton("查看选中包日志")
        self.view_pkg_log_btn.clicked.connect(self._view_pkg_log)
        log_row.addWidget(self.view_pkg_log_btn)
        self.view_last_log_btn = QPushButton("查看最近命令输出")
        self.view_last_log_btn.clicked.connect(self._view_last_log)
        log_row.addWidget(self.view_last_log_btn)
        adv_layout.addLayout(log_row)

        layout.addWidget(self.adv_container)
        layout.addStretch()

    def _toggle_advanced(self, checked: bool):
        """展开/收起高级设置"""
        self.adv_container.setVisible(checked)
        if checked:
            self.adv_toggle_btn.setText("▾ 高级设置（点击收起）")
        else:
            self.adv_toggle_btn.setText("▸ 高级设置（自定义安装 · 环境终端 · 命令日志）")

    def _populate_pkg_table(self):
        """填充内置软件包列表（版本列留空，安装后显示实际版本）"""
        self.pkg_table.setRowCount(len(PACKAGES))
        for i, pkg in enumerate(PACKAGES):
            self.pkg_table.setItem(i, 0, QTableWidgetItem(pkg.name))
            self.pkg_table.setItem(i, 1, QTableWidgetItem(""))  # 实际版本，安装后查询填入
            type_item = QTableWidgetItem("★ 必需" if pkg.required else "可选")
            if pkg.required:
                type_item.setForeground(QColor("#c0392b"))
                type_item.setToolTip(pkg.description or "De Novo 流程必需")
            else:
                type_item.setForeground(QColor("#7f8c8d"))
                type_item.setToolTip(pkg.description or "")
            self.pkg_table.setItem(i, 2, type_item)
            self.pkg_table.setItem(i, 3, QTableWidgetItem("未安装"))

    def _add_custom_pkg_row(self, pkg_name: str, version: str = "", status: str = "已安装"):
        """把用户自定义安装的软件包动态添加到表格末尾"""
        row = self.pkg_table.rowCount()
        self.pkg_table.insertRow(row)
        self.pkg_table.setItem(row, 0, QTableWidgetItem(pkg_name))
        self.pkg_table.setItem(row, 1, QTableWidgetItem(version))
        type_item = QTableWidgetItem("自定义")
        type_item.setForeground(QColor("#2980b9"))
        self.pkg_table.setItem(row, 2, type_item)
        status_item = QTableWidgetItem(status)
        status_item.setForeground(QColor(COLORS["success"] if status == "已安装" else COLORS["error"]))
        self.pkg_table.setItem(row, 3, status_item)

    def _find_pkg_row(self, pkg_name: str) -> int:
        """按包名查找表格行号（找不到返回 -1）"""
        for row in range(self.pkg_table.rowCount()):
            item = self.pkg_table.item(row, 0)
            if item and item.text().lower() == pkg_name.lower():
                return row
        return -1

    def get_env_manager(self) -> CondaEnvManager:
        if self.env_manager is None:
            conda_path = self.conda_path_edit.text().strip()
            env_name = self.env_name_edit.text().strip() or "rna2unigene_condaenv"
            self.env_manager = CondaEnvManager(env_name, conda_path)
            self.config.set("conda_env_name", env_name)
        return self.env_manager

    def _detect_conda(self):
        env = self.get_env_manager()
        ok, info = env.is_conda_installed()

        if ok:
            self.conda_status_label.setText(f"✓ {info}")
            self.conda_status_label.setStyleSheet(f"color: {COLORS['success']}; font-weight: bold;")
            self.create_env_btn.setEnabled(True)
            self.conda_path_edit.setText(env.conda_exe)
            if env.env_exists():
                self.conda_status_label.setText(f"✓ {info}  |  环境 '{env.env_name}' 已存在")
                self.create_env_btn.setText("重建环境")
                self._env_ready = True
                self._refresh_env_buttons()
        elif info == "NEED_INSTALL":
            # 需要自动部署本地 Conda
            self.conda_path_edit.setText(os.path.join(get_local_conda_dir(), "bin", "conda"))
            self.conda_status_label.setText("未找到 Conda — 点击下方按钮自动部署（不影响系统）")
            self.conda_status_label.setStyleSheet(f"color: {COLORS['warning']}; font-weight: bold;")
            self.create_env_btn.setText("自动部署 Conda")
            self.create_env_btn.setEnabled(True)
            self._env_ready = False
            self._refresh_env_buttons()
        else:
            self.conda_status_label.setText(f"✗ {info}")
            self.conda_status_label.setStyleSheet(f"color: {COLORS['error']};")

    def _create_env(self):
        env = self.get_env_manager()
        self.create_env_btn.setEnabled(False)

        # 如果 conda 不可用，先自动部署
        ok, info = env.is_conda_installed()
        if not ok:
            self.conda_status_label.setText("正在下载 Miniconda（约100MB，仅首次需要）...")
            self.conda_status_label.setStyleSheet(f"color: {COLORS['running']}; font-weight: bold;")
            QApplication.processEvents()

            def progress(msg):
                self.conda_status_label.setText(msg)
                QApplication.processEvents()

            ok, msg = env.ensure_conda_ready(progress)
            if not ok:
                self.conda_status_label.setText(f"✗ Conda 部署失败: {msg[:100]}")
                self.conda_status_label.setStyleSheet(f"color: {COLORS['error']};")
                self.create_env_btn.setEnabled(True)
                return
            self.conda_path_edit.setText(env.conda_exe)
            self.conda_status_label.setText(f"✓ 本地 Conda 就绪 ({get_local_conda_dir()})")
            self.conda_status_label.setStyleSheet(f"color: {COLORS['success']}; font-weight: bold;")
            QApplication.processEvents()

        # 创建分析环境
        self.conda_status_label.setText("正在创建分析环境...")
        self.conda_status_label.setStyleSheet(f"color: {COLORS['running']};")
        QApplication.processEvents()

        ok, msg = env.create_env()
        if ok:
            self.conda_status_label.setText(f"✓ 环境 '{env.env_name}' 创建成功")
            self.conda_status_label.setStyleSheet(f"color: {COLORS['success']}; font-weight: bold;")
            self._env_ready = True
            self._refresh_env_buttons()
        else:
            self.conda_status_label.setText(f"✗ 创建失败: {msg[:100]}")
            self.conda_status_label.setStyleSheet(f"color: {COLORS['error']};")
        self.create_env_btn.setEnabled(True)

    def _install_packages(self):
        env = self.get_env_manager()
        for i in range(len(PACKAGES)):
            self.pkg_table.item(i, 3).setText("等待安装...")
            self.pkg_table.item(i, 3).setForeground(QColor("#7f8c8d"))
        self._set_env_busy(True, "正在安装软件包")

        def task_fn():
            results = env.install_all_packages()
            self._install_results = results
            ok = all(s for _, s, _ in results)
            return ok, f"成功 {sum(1 for _, s, _ in results if s)}/{len(results)}"

        self._run_env_task(task_fn, self._on_install_done)

    def _on_install_done(self, ok, msg):
        env = self.get_env_manager()
        results = self._install_results
        for i, (name, success, _) in enumerate(results):
            if i >= len(PACKAGES):
                continue
            status_item = self.pkg_table.item(i, 3)
            status_item.setText("✓ 已安装" if success else "✗ 失败")
            status_item.setForeground(QColor(COLORS["success"] if success else COLORS["error"]))
            if success:
                ver = env.get_package_version(name)
                if ver:
                    self.pkg_table.item(i, 1).setText(ver)

        ok_count = sum(1 for _, s, _ in results if s)
        QMessageBox.information(
            self, "安装完成",
            f"软件包安装完成\n成功: {ok_count}/{len(results)}\n"
            + ("全部安装成功！" if ok_count == len(results)
               else "失败的软件包可在表格中选中后单独重装，或查看日志定位问题。")
        )

    def _retry_package(self, item=None):
        """重装选中的软件包（支持表格选中多行 / 双击单行）"""
        # 双击触发时 item 为 QTableWidgetItem；按钮触发时为 None
        # 注意: 不能用 `is not None` 判断，因为按钮 clicked 信号可能传入 False
        if isinstance(item, QTableWidgetItem):
            selected_rows = [item.row()]
        else:
            selected_rows = sorted(set(
                idx.row() for idx in self.pkg_table.selectedIndexes()
            ))
            if not selected_rows:
                QMessageBox.information(
                    self, "提示", "请先在表格中选中要重装的软件包（可按住 Ctrl 多选）"
                )
                return

        # 收集要重装的包名
        pkg_names = []
        for row in selected_rows:
            pkg_item = self.pkg_table.item(row, 0)
            if pkg_item:
                pkg_names.append(pkg_item.text().strip())
        if not pkg_names:
            return

        # 标记"安装中"状态
        for row in selected_rows:
            status_item = self.pkg_table.item(row, 3)
            if status_item:
                status_item.setText("安装中...")
                status_item.setForeground(QColor(COLORS["running"]))

        env = self.get_env_manager()
        self._set_env_busy(True, "正在重装软件包")

        def task_fn():
            results = []
            for pkg_name in pkg_names:
                # 内置包走标准安装；自定义包走通用安装
                pkg = next((p for p in PACKAGES if p.name == pkg_name), None)
                if pkg is not None:
                    success, msg = env.install_package(pkg)
                else:
                    success, msg = env.install_custom_package(pkg_name)
                results.append((pkg_name, success, msg))
            self._retry_results = results
            ok = all(s for _, s, _ in results)
            return ok, f"成功 {sum(1 for _, s, _ in results if s)}/{len(results)}"

        self._run_env_task(task_fn, self._on_retry_done)

    def _on_retry_done(self, ok, msg):
        env = self.get_env_manager()
        results = self._retry_results
        for pkg_name, success, _ in results:
            row = self._find_pkg_row(pkg_name)
            if row < 0:
                continue
            status_item = self.pkg_table.item(row, 3)
            if status_item:
                status_item.setText("✓ 已安装" if success else "✗ 失败")
                status_item.setForeground(
                    QColor(COLORS["success"] if success else COLORS["error"])
                )
            if success:
                ver = env.get_package_version(pkg_name)
                ver_item = self.pkg_table.item(row, 1)
                if ver_item and ver:
                    ver_item.setText(ver)

        ok_count = sum(1 for _, s, _ in results if s)
        QMessageBox.information(
            self, "重装完成",
            f"重装完成\n成功: {ok_count}/{len(results)}\n"
            + ("全部成功！" if ok_count == len(results)
               else "失败的软件包可再次选中后重装，或在高级设置中查看日志。")
        )

    def _verify_packages(self):
        env = self.get_env_manager()
        self._set_env_busy(True, "正在验证软件包")

        def task_fn():
            results = env.verify_all_packages()
            self._verify_results = results
            ok = all(r[1] for r in results)
            return ok, f"成功 {sum(1 for r in results if r[1])}/{len(results)}"

        self._run_env_task(task_fn, self._on_verify_done)

    def _on_verify_done(self, ok, msg):
        env = self.get_env_manager()
        results = self._verify_results
        for i, (name, success, _) in enumerate(results):
            row = self._find_pkg_row(name)
            if row < 0:
                continue
            item = self.pkg_table.item(row, 3)
            if success:
                item.setText("✓ 已验证")
                item.setForeground(QColor(COLORS["success"]))
            else:
                item.setText("✗ 未通过")
                item.setForeground(QColor(COLORS["error"]))
            # 顺带回填实际版本
            ver = env.get_package_version(name)
            if ver:
                self.pkg_table.item(row, 1).setText(ver)
        QMessageBox.information(
            self, "验证完成",
            f"软件包验证完成\n{msg}\n具体状态请查看表格。"
        )

    # ---- 卸载 ----

    def _uninstall_package(self):
        """卸载选中的软件包"""
        rows = sorted(set(idx.row() for idx in self.pkg_table.selectedIndexes()))
        if not rows:
            QMessageBox.information(self, "提示", "请先在表格中选中要卸载的软件包（可按住 Ctrl 多选）")
            return

        pkg_names = []
        for row in rows:
            pkg_item = self.pkg_table.item(row, 0)
            if pkg_item:
                pkg_names.append(pkg_item.text().strip())

        reply = QMessageBox.question(
            self, "确认卸载",
            f"确定要卸载以下软件包吗？\n\n{chr(10).join(pkg_names)}",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        # 标记"卸载中"状态
        for row in rows:
            status_item = self.pkg_table.item(row, 3)
            if status_item:
                status_item.setText("卸载中...")
                status_item.setForeground(QColor(COLORS["running"]))

        env = self.get_env_manager()
        self._set_env_busy(True, "正在卸载软件包")

        def task_fn():
            results = []
            for pkg_name in pkg_names:
                success, msg = env.uninstall_package(pkg_name)
                results.append((pkg_name, success, msg))
            self._uninstall_results = results
            ok = all(s for _, s, _ in results)
            return ok, f"成功 {sum(1 for _, s, _ in results if s)}/{len(results)}"

        self._run_env_task(task_fn, self._on_uninstall_done)

    def _on_uninstall_done(self, ok, msg):
        results = self._uninstall_results
        for pkg_name, success, _ in results:
            row = self._find_pkg_row(pkg_name)
            if row < 0:
                continue
            ver_item = self.pkg_table.item(row, 1)
            status_item = self.pkg_table.item(row, 3)
            if success:
                if ver_item:
                    ver_item.setText("")
                if status_item:
                    status_item.setText("未安装")
                    status_item.setForeground(QColor("#7f8c8d"))
            else:
                if status_item:
                    status_item.setText("✗ 卸载失败")
                    status_item.setForeground(QColor(COLORS["error"]))

        ok_count = sum(1 for _, s, _ in results if s)
        QMessageBox.information(
            self, "卸载完成",
            f"卸载完成\n成功: {ok_count}/{len(results)}"
        )

    def _uninstall_all(self):
        """卸载全部：直接删除整个环境（最干净）"""
        reply = QMessageBox.question(
            self, "确认删除环境",
            "此操作将删除整个分析环境（等同卸载全部软件包，包括 Python 和所有依赖）。\n\n"
            "删除后需要重新「创建环境」并重新安装软件包。\n"
            "确定继续吗？",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        env = self.get_env_manager()
        self._set_env_busy(True, "正在删除环境")

        def task_fn():
            return env.remove_env()

        self._run_env_task(task_fn, self._on_uninstall_all_done)

    def _on_uninstall_all_done(self, ok, msg):
        if not ok:
            QMessageBox.warning(self, "删除失败", msg)
            return

        # 重置表格：清空版本和状态
        for row in range(self.pkg_table.rowCount()):
            ver_item = self.pkg_table.item(row, 1)
            if ver_item:
                ver_item.setText("")
            status_item = self.pkg_table.item(row, 3)
            if status_item:
                status_item.setText("未安装")
                status_item.setForeground(QColor("#7f8c8d"))

        # 环境已删除，恢复初始按钮状态
        self._env_ready = False
        self._refresh_env_buttons()
        self.create_env_btn.setText("创建环境")
        self.create_env_btn.setEnabled(True)
        self.conda_status_label.setText("✓ 环境已删除，点击「创建环境」重新创建")
        self.conda_status_label.setStyleSheet(f"color: {COLORS['warning']}; font-weight: bold;")

        QMessageBox.information(
            self, "环境已删除",
            "分析环境已删除。\n\n"
            "接下来请点击「创建环境」重新创建环境，"
            "然后「安装全部软件包」。"
        )

    # ---- 高级设置 ----

    def _install_custom(self):
        """安装用户自定义的软件包"""
        spec = self.custom_pkg_edit.text().strip()
        if not spec:
            QMessageBox.information(self, "提示", "请输入要安装的软件包名称")
            return

        # 提取纯包名（去掉版本约束），用于表格行
        base_name = spec.split("=")[0].split(">")[0].split("<")[0].strip()

        env = self.get_env_manager()
        self._set_env_busy(True, f"正在安装 {spec}")
        self.adv_log_view.appendPlainText(f"\n$ 自定义安装: {spec}")

        def task_fn():
            return env.install_custom_package(spec)

        self._run_env_task(task_fn, lambda ok, msg: self._on_custom_install_done(ok, msg, base_name))

    def _on_custom_install_done(self, ok, msg, base_name):
        env = self.get_env_manager()
        self.adv_log_view.appendPlainText(env.last_log or msg)

        # 把自定义包加入表格（已存在则更新版本/状态）
        ver = env.get_package_version(base_name) if ok else ""
        row = self._find_pkg_row(base_name)
        if row < 0:
            self._add_custom_pkg_row(
                base_name, ver,
                "✓ 已安装" if ok else "✗ 失败"
            )
        else:
            ver_item = self.pkg_table.item(row, 1)
            if ver_item and ver:
                ver_item.setText(ver)
            status_item = self.pkg_table.item(row, 3)
            status_item.setText("✓ 已安装" if ok else "✗ 失败")
            status_item.setForeground(
                QColor(COLORS["success"] if ok else COLORS["error"])
            )

        if ok:
            QMessageBox.information(self, "安装完成", msg)
        else:
            QMessageBox.warning(self, "安装失败", f"{msg}\n\n详细日志见「高级设置」日志区")

    def _view_pkg_log(self):
        """查看选中软件包的安装日志"""
        rows = sorted(set(idx.row() for idx in self.pkg_table.selectedIndexes()))
        if not rows:
            QMessageBox.information(self, "提示", "请先在表格中选中要查看日志的软件包")
            return

        env = self.get_env_manager()
        lines = []
        for row in rows:
            pkg_item = self.pkg_table.item(row, 0)
            if not pkg_item:
                continue
            pkg_name = pkg_item.text().strip()
            lines.append(f"===== {pkg_name} 最近一次安装日志 =====\n")
            lines.append(env.get_package_log(pkg_name))
            lines.append("")
        self.adv_log_view.setPlainText("\n".join(lines))

    def _view_last_log(self):
        """查看最近一次 conda 命令的完整输出"""
        env = self.get_env_manager()
        if not env.last_log:
            self.adv_log_view.setPlainText("（暂无命令记录，请先执行安装/验证操作）")
            return
        self.adv_log_view.setPlainText(
            f"$ {env.last_cmd}\n\n{env.last_log}"
        )

    # ---- 环境终端（pty 实时终端） ----

    def _term_bash_exe(self) -> str:
        """获取分析环境中的 bash 路径（等同 conda run）"""
        env = self.get_env_manager()
        env_path = env.get_env_path()
        if env_path and os.path.isdir(env_path):
            bash = os.path.join(env_path, "bin", "bash")
            if os.path.isfile(bash):
                return bash
        return "/bin/bash"

    def _on_terminal_enter(self):
        """输入框回车：空闲时执行命令，运行中则发送输入给进程（交互确认）"""
        text = self.term_input.text()
        if self._term_worker is not None and self._term_worker.isRunning():
            # 运行中：把输入发给进程（如 conda 询问 y/n）
            if text.strip():
                if self._term_worker.send_input(text.strip()):
                    self.adv_log_view.appendPlainText(f"  ↳ 已发送: {text.strip()}")
                else:
                    self.adv_log_view.appendPlainText("  ↳ 发送失败（进程已结束）")
            self.term_input.clear()
            return

        cmd = text.strip()
        if not cmd:
            return

        env = self.get_env_manager()
        # 回显命令（终端风格）
        self.adv_log_view.appendPlainText(f"$ {cmd}")
        self.term_input.commit_command(cmd)
        self.term_input.setEnabled(False)
        self._set_env_busy(True, f"正在执行命令: {cmd[:40]}")

        worker = TerminalWorker(self._term_bash_exe(), cmd)
        worker.output.connect(self._on_terminal_output)
        worker.terminated.connect(self._on_terminal_done)
        self._term_worker = worker
        worker.start()

    @pyqtSlot(str)
    def _on_terminal_output(self, text: str):
        """实时输出追加到终端区"""
        self.adv_log_view.appendPlainText(text)
        self.adv_log_view.moveCursor(QTextCursor.End)

    @pyqtSlot(bool, str)
    def _on_terminal_done(self, ok, msg):
        # 先清空忙碌状态（恢复按钮），再补结束标记
        self._set_env_busy(False)
        self.adv_log_view.appendPlainText(f"[进程结束 {msg}]")
        self.adv_log_view.moveCursor(QTextCursor.End)
        self.term_input.setFocus()
        if ok:
            self._refresh_versions_from_env()
        self._term_worker = None

    # ---- Tab 自动补全 ----

    @pyqtSlot(str)
    def _on_terminal_tab(self, text: str):
        """Tab 补全：命令 / conda 子命令 / 文件路径"""
        # 命令运行中不响应 Tab（避免干扰）
        if self._term_worker is not None and self._term_worker.isRunning():
            return

        before = text[:self.term_input.cursorPosition()]
        after = text[self.term_input.cursorPosition():]
        words = before.split()
        if not words:
            return
        token = words[-1]

        candidates = self._get_tab_candidates(words, token)
        if not candidates:
            return

        candidates = sorted(set(candidates))

        if len(candidates) == 1:
            self._apply_completion(before, after, token, candidates[0] + " ")
        else:
            # 找公共前缀
            common = os.path.commonprefix(candidates)
            if len(common) > len(token):
                self._apply_completion(before, after, token, common)
            else:
                # 无公共前缀：终端风格显示候选
                self.adv_log_view.appendPlainText(
                    "  候选: " + "  ".join(candidates)
                )
                self.adv_log_view.moveCursor(QTextCursor.End)

    def _get_tab_candidates(self, words: List[str], token: str) -> List[str]:
        """获取补全候选列表"""
        candidates = []
        bash = self._term_bash_exe()

        if len(words) <= 1:
            # 命令位置：compgen -c 补全命令
            out = self._run_compgen(bash, "c", token)
            candidates += out
        else:
            # 参数位置
            if words[0] == "conda" and len(words) == 2:
                # conda 子命令补全
                candidates += [
                    sub for sub in CONDA_SUBCOMMANDS if sub.startswith(token)
                ]
            # 文件/目录补全
            candidates += self._run_compgen(bash, "f", token)
        return candidates

    @staticmethod
    def _run_compgen(bash: str, kind: str, token: str) -> List[str]:
        """在环境中执行 compgen 查询补全候选"""
        try:
            out = subprocess.run(
                [bash, "-c", f'compgen -{kind} -- "{token}" 2>/dev/null'],
                capture_output=True, text=True, timeout=5,
            )
            return [line for line in out.stdout.splitlines() if line]
        except Exception:
            return []

    def _apply_completion(self, before: str, after: str, token: str, replacement: str):
        """应用补全结果到输入框"""
        head = before[:len(before) - len(token)]
        new_text = head + replacement + after
        self.term_input.setText(new_text)
        self.term_input.setCursorPosition(len(head) + len(replacement))

    def _refresh_versions_from_env(self):
        """从环境中读取所有已安装包的版本，刷新表格"""
        env = self.get_env_manager()
        for row in range(self.pkg_table.rowCount()):
            pkg_item = self.pkg_table.item(row, 0)
            if not pkg_item:
                continue
            pkg_name = pkg_item.text().strip()
            ver = env.get_package_version(pkg_name)
            if ver:
                self.pkg_table.item(row, 1).setText(ver)
                # 未标记状态的顺带标记
                status_item = self.pkg_table.item(row, 3)
                if status_item and status_item.text() in ("未安装", "等待安装..."):
                    status_item.setText("✓ 已安装")
                    status_item.setForeground(QColor(COLORS["success"]))


# ============================================================
# 样本配置页
# ============================================================

class SampleConfigPage(QWidget):
    """样本配置页面"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        group = QGroupBox("样本信息（Trinity samples_file 格式）")
        group.setStyleSheet(group_style())
        g_layout = QVBoxLayout(group)

        # 说明
        hint = QLabel("格式: 条件/分组 | 重复名 | R1文件路径 | R2文件路径")
        hint.setStyleSheet("color: #888; font-size: 12px; margin-bottom: 8px;")
        g_layout.addWidget(hint)

        # 样本表格
        self.sample_table = QTableWidget()
        self.sample_table.setColumnCount(4)
        self.sample_table.setHorizontalHeaderLabels(["条件/分组", "重复名", "R1 FASTQ 路径", "R2 FASTQ 路径"])
        self.sample_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.sample_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.sample_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.sample_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.sample_table.verticalHeader().setVisible(False)
        self.sample_table.setAlternatingRowColors(True)
        g_layout.addWidget(self.sample_table)

        # 按钮
        btn_layout = QHBoxLayout()
        self.add_row_btn = QPushButton("+ 添加样本")
        self.add_row_btn.clicked.connect(self._add_row)
        self.del_row_btn = QPushButton("− 删除选中")
        self.del_row_btn.clicked.connect(self._delete_row)
        self.import_btn = QPushButton("从 samples_file 导入")
        self.import_btn.clicked.connect(self._import_samples_file)
        self.clear_btn = QPushButton("清空")
        self.clear_btn.clicked.connect(lambda: self.sample_table.setRowCount(0))

        btn_layout.addWidget(self.add_row_btn)
        btn_layout.addWidget(self.del_row_btn)
        btn_layout.addWidget(self.import_btn)
        btn_layout.addWidget(self.clear_btn)
        btn_layout.addStretch()
        g_layout.addLayout(btn_layout)

        layout.addWidget(group)
        layout.addStretch()

    def _add_row(self):
        row = self.sample_table.rowCount()
        self.sample_table.insertRow(row)
        for col in range(4):
            item = QTableWidgetItem("")
            self.sample_table.setItem(row, col, item)

    def _delete_row(self):
        rows = set(idx.row() for idx in self.sample_table.selectedIndexes())
        for row in sorted(rows, reverse=True):
            self.sample_table.removeRow(row)

    def _import_samples_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 Trinity samples_file", "",
            "文本文件 (*.txt *.tsv *.csv);;所有文件 (*)"
        )
        if not path:
            return

        self.sample_table.setRowCount(0)
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) >= 4:
                    row = self.sample_table.rowCount()
                    self.sample_table.insertRow(row)
                    self.sample_table.setItem(row, 0, QTableWidgetItem(parts[0]))
                    self.sample_table.setItem(row, 1, QTableWidgetItem(parts[1]))
                    self.sample_table.setItem(row, 2, QTableWidgetItem(parts[2]))
                    self.sample_table.setItem(row, 3, QTableWidgetItem(parts[3]))

    def get_samples(self) -> List[SampleInfo]:
        """获取所有样本信息"""
        samples = []
        for row in range(self.sample_table.rowCount()):
            group = self.sample_table.item(row, 0)
            repl = self.sample_table.item(row, 1)
            r1 = self.sample_table.item(row, 2)
            r2 = self.sample_table.item(row, 3)

            if group and repl and r1 and r2:
                g = group.text().strip()
                r = repl.text().strip()
                r1_path = r1.text().strip()
                r2_path = r2.text().strip()
                if g and r and r1_path:
                    samples.append(SampleInfo(
                        group=g, replicate=r,
                        r1_path=r1_path, r2_path=r2_path
                    ))
        return samples

    def has_samples(self) -> bool:
        return len(self.get_samples()) > 0


# ============================================================
# 参数配置页
# ============================================================

class ParamConfigPage(QWidget):
    """参数配置页面"""

    def __init__(self, config: ConfigManager, parent=None):
        super().__init__(parent)
        self.config = config
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # ---- 基本参数 ----
        group1 = QGroupBox("基本参数")
        group1.setStyleSheet(group_style())
        g1 = QFormLayout(group1)

        self.work_dir_edit = QLineEdit()
        self.work_dir_edit.setPlaceholderText("选择分析输出目录...")
        browse_btn = QPushButton("浏览...")
        browse_btn.clicked.connect(self._browse_work_dir)
        dir_layout = QHBoxLayout()
        dir_layout.addWidget(self.work_dir_edit)
        dir_layout.addWidget(browse_btn)
        g1.addRow("工作目录:", dir_layout)

        self.prefix_edit = QLineEdit()
        self.prefix_edit.setText(self.config.species_prefix)
        self.prefix_edit.setPlaceholderText("如 Hvi")
        g1.addRow("物种前缀:", self.prefix_edit)

        self.gene_prefix_edit = QLineEdit()
        self.gene_prefix_edit.setText(self.config.gene_prefix)
        self.gene_prefix_edit.setPlaceholderText("如 Uni")
        g1.addRow("基因前缀:", self.gene_prefix_edit)

        self.thread_spin = QSpinBox()
        self.thread_spin.setRange(1, 128)
        self.thread_spin.setValue(self.config.default_threads)
        g1.addRow("CPU 线程:", self.thread_spin)

        layout.addWidget(group1)

        # ---- Fastp 参数 ----
        group2 = QGroupBox("Fastp 过滤参数")
        group2.setStyleSheet(group_style())
        g2 = QFormLayout(group2)

        fp = self.config.fastp_params()
        self.fp_q_spin = QSpinBox()
        self.fp_q_spin.setRange(10, 40)
        self.fp_q_spin.setValue(fp.get("quality_threshold", 20))
        g2.addRow("质量阈值 (-q):", self.fp_q_spin)

        self.fp_l_spin = QSpinBox()
        self.fp_l_spin.setRange(20, 200)
        self.fp_l_spin.setValue(fp.get("min_length", 50))
        g2.addRow("最小长度 (-l):", self.fp_l_spin)

        layout.addWidget(group2)

        # ---- Trinity 参数 ----
        group3 = QGroupBox("Trinity 组装参数")
        group3.setStyleSheet(group_style())
        g3 = QFormLayout(group3)

        self.tr_mem_edit = QLineEdit()
        self.tr_mem_edit.setText(self.config.trinity_params().get("max_memory", "50G"))
        g3.addRow("最大内存 (--max_memory):", self.tr_mem_edit)

        layout.addWidget(group3)

        # ---- CD-HIT 参数 ----
        group4 = QGroupBox("CD-HIT 去冗余参数")
        group4.setStyleSheet(group_style())
        g4 = QFormLayout(group4)

        ch = self.config.cd_hit_params()
        self.ch_identity_spin = QDoubleSpinBox()
        self.ch_identity_spin.setRange(0.70, 1.0)
        self.ch_identity_spin.setSingleStep(0.05)
        self.ch_identity_spin.setValue(ch.get("identity_threshold", 0.80))
        self.ch_identity_spin.setDecimals(2)
        g4.addRow("相似性阈值 (-c):", self.ch_identity_spin)

        layout.addWidget(group4)

        # ---- 步骤选择 ----
        group5 = QGroupBox("执行步骤选择")
        group5.setStyleSheet(group_style())
        g5_layout = QVBoxLayout(group5)

        self.step_checkboxes = {}
        for step in PIPELINE_STEPS:
            cb = QCheckBox(f"{step['name']} - {step['description']}")
            cb.setChecked(True)
            cb.setEnabled(False)  # de novo 流程所有步骤都是必需的
            self.step_checkboxes[step["id"]] = cb
            g5_layout.addWidget(cb)

        layout.addWidget(group5)
        layout.addStretch()

    def _browse_work_dir(self):
        path = QFileDialog.getExistingDirectory(self, "选择工作目录")
        if path:
            self.work_dir_edit.setText(path)

    def get_work_dir(self) -> str:
        return self.work_dir_edit.text().strip()

    def get_species_prefix(self) -> str:
        return self.prefix_edit.text().strip() or "Hvi"

    def get_gene_prefix(self) -> str:
        return self.gene_prefix_edit.text().strip() or "Uni"

    def get_threads(self) -> int:
        return self.thread_spin.value()

    def get_active_steps(self) -> List[str]:
        return [sid for sid, cb in self.step_checkboxes.items() if cb.isChecked()]

    def get_extra_params(self) -> dict:
        return {
            "fastp_quality": self.fp_q_spin.value(),
            "fastp_min_length": self.fp_l_spin.value(),
            "trinity_max_memory": self.tr_mem_edit.text().strip() or "50G",
            "cd_hit_identity": self.ch_identity_spin.value(),
        }


# ============================================================
# 主窗口
# ============================================================

class MainWindow(QMainWindow):
    """转录组 de novo 组装软件 - 主窗口"""

    def __init__(self, config: ConfigManager):
        super().__init__()
        self.config = config
        self.worker: Optional[AnalysisWorker] = None
        self._setup_ui()
        self._load_window_state()

    def _setup_ui(self):
        self.setWindowTitle(f"转录组分析软件 v{__version__}")
        self.setMinimumSize(1100, 720)
        self.resize(1200, 800)

        # 设置应用图标
        icon_path = get_app_icon()
        if icon_path:
            from PyQt5.QtGui import QIcon
            self.setWindowIcon(QIcon(icon_path))

        # 中央控件
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ---- 顶部模块导航 ----
        self.module_bar = ModuleNavBar()
        self.module_bar.module_selected.connect(self._on_module_changed)
        main_layout.addWidget(self.module_bar)

        # ---- 模块堆叠容器 ----
        self.module_stack = QStackedWidget()
        main_layout.addWidget(self.module_stack, 1)

        # ======== 模块1: De Novo 组装（现有完整功能） ========
        denovo_widget = QWidget()
        denovo_layout = QVBoxLayout(denovo_widget)
        denovo_layout.setContentsMargins(0, 0, 0, 0)
        denovo_layout.setSpacing(0)

        # 顶部水平区域
        top_splitter = QSplitter(Qt.Horizontal)

        # 左侧：步骤导航
        self.step_list = StepListWidget()
        self.step_list.populate(PIPELINE_STEPS)
        top_splitter.addWidget(self.step_list)

        # 右侧：Tab 页面
        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet(f"""
            QTabWidget::pane {{
                border: 1px solid {COLORS['border']};
                background: {COLORS['card_bg']};
            }}
            QTabBar::tab {{
                padding: 8px 20px;
                margin-right: 2px;
            }}
            QTabBar::tab:selected {{
                border-bottom: 3px solid {COLORS['primary_btn']};
                font-weight: bold;
            }}
        """)

        self.env_page = EnvSetupPage(self.config)
        self.sample_page = SampleConfigPage()
        self.param_page = ParamConfigPage(self.config)

        self.tab_widget.addTab(self.env_page, "1. 环境设置")
        self.tab_widget.addTab(self.sample_page, "2. 样本配置")
        self.tab_widget.addTab(self.param_page, "3. 参数配置")

        top_splitter.addWidget(self.tab_widget)
        top_splitter.setStretchFactor(0, 0)
        top_splitter.setStretchFactor(1, 1)

        denovo_layout.addWidget(top_splitter, 1)

        # 日志输出
        log_frame = QFrame()
        log_frame.setFrameShape(QFrame.StyledPanel)
        log_frame.setMaximumHeight(220)
        log_layout = QVBoxLayout(log_frame)
        log_layout.setContentsMargins(8, 4, 8, 4)

        log_header = QHBoxLayout()
        log_label = QLabel("运行日志")
        log_label.setStyleSheet("font-weight: bold; color: #2c3e50;")
        log_header.addWidget(log_label)
        log_header.addStretch()
        self.clear_log_btn = QPushButton("清空")
        self.clear_log_btn.clicked.connect(self._clear_log)
        self.clear_log_btn.setFixedSize(60, 24)
        log_header.addWidget(self.clear_log_btn)
        log_layout.addLayout(log_header)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        self.log_view.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: #1e1e1e;
                color: #d4d4d4;
                font-family: "Consolas", "Source Code Pro", "DejaVu Sans Mono", monospace;
                font-size: 12px;
                border: 1px solid #333;
                border-radius: 4px;
            }}
        """)
        log_layout.addWidget(self.log_view)

        denovo_layout.addWidget(log_frame, 0)

        # 进度条与按钮
        control_frame = QFrame()
        control_frame.setStyleSheet(f"""
            QFrame {{ background-color: {COLORS['card_bg']}; border-top: 1px solid {COLORS['border']}; }}
        """)
        control_layout = QHBoxLayout(control_frame)
        control_layout.setContentsMargins(16, 8, 16, 8)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
                text-align: center;
                height: 22px;
            }}
            QProgressBar::chunk {{
                background-color: {COLORS['primary_btn']};
                border-radius: 3px;
            }}
        """)
        control_layout.addWidget(self.progress_bar, 1)

        self.run_all_btn = QPushButton("▶ 运行全部流程")
        self.run_all_btn.clicked.connect(self._on_run_all)
        self.run_all_btn.setStyleSheet(self._btn_style(COLORS["primary_btn"]))
        control_layout.addWidget(self.run_all_btn)

        self.stop_btn = QPushButton("■ 停止")
        self.stop_btn.clicked.connect(self._on_stop)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet(self._btn_style(COLORS["danger_btn"]))
        control_layout.addWidget(self.stop_btn)

        denovo_layout.addWidget(control_frame, 0)

        self.module_stack.addWidget(denovo_widget)

        # ======== 模块2: 序列比对（占位） ========
        self.align_page = ModulePlaceholderPage(
            "测序数据比对",
            "将转录组 reads 比对到参考基因组或转录组，获得基因表达定量数据。",
            [
                ("参考序列索引构建", "HISAT2 / STAR 建立参考基因组索引"),
                ("序列比对", "将质控后的 reads 比对到参考序列 (HISAT2 / STAR / Bowtie2)"),
                ("比对结果处理", "SAM → BAM 转换、排序、去重 (Samtools)"),
                ("表达定量", "featureCounts / HTSeq 基因计数定量"),
            ],
        )
        self.module_stack.addWidget(self.align_page)

        # ======== 模块3: 差异表达分析（占位） ========
        self.deg_page = ModulePlaceholderPage(
            "基因差异表达分析",
            "基于定量结果筛选差异表达基因，并进行功能富集分析。",
            [
                ("差异表达分析", "DESeq2 / edgeR / limma 差异基因筛选"),
                ("结果可视化", "火山图、MA图、热图、PCA聚类图"),
                ("GO 富集分析", "基因本体功能富集分析"),
                ("KEGG 通路分析", "代谢通路富集分析"),
            ],
        )
        self.module_stack.addWidget(self.deg_page)

        # ---- 状态栏 ----
        self.statusBar().showMessage("就绪 | 请先设置环境并配置样本")

        # ---- 菜单栏 ----
        menubar = self.menuBar()
        file_menu = menubar.addMenu("文件")
        save_action = QAction("保存配置", self)
        save_action.triggered.connect(self._save_config)
        file_menu.addAction(save_action)
        load_action = QAction("加载配置", self)
        load_action.triggered.connect(self._load_config)
        file_menu.addAction(load_action)
        file_menu.addSeparator()
        exit_action = QAction("退出", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        help_menu = menubar.addMenu("帮助")
        about_action = QAction("关于", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _btn_style(self, color: str) -> str:
        return f"""
            QPushButton {{
                background-color: {color};
                color: white;
                padding: 8px 20px;
                border-radius: 4px;
                font-weight: bold;
                border: none;
            }}
            QPushButton:hover {{ opacity: 0.9; }}
            QPushButton:disabled {{ background-color: #bdc3c7; }}
        """

    # ---- 日志 ----

    def _log(self, msg: str):
        self.log_view.appendPlainText(msg)
        # 自动滚动到底部
        self.log_view.moveCursor(QTextCursor.End)

    def _clear_log(self):
        self.log_view.clear()

    # ---- 模块切换 ----

    def _on_module_changed(self, idx: int):
        """切换分析模块"""
        self.module_stack.setCurrentIndex(idx)
        module_names = ["De Novo 组装", "序列比对", "差异表达分析"]
        if idx == 0:
            self.statusBar().showMessage("就绪 | De Novo 组装模块")
        else:
            self.statusBar().showMessage(
                f"{module_names[idx]} 模块开发中，将在后续版本开放"
            )

    # ---- 运行流程 ----

    def _on_run_all(self):
        """运行全部流程"""
        # 验证配置
        work_dir = self.param_page.get_work_dir()
        if not work_dir:
            QMessageBox.warning(self, "提示", "请先设置工作目录（参数配置页）")
            self.tab_widget.setCurrentIndex(2)
            return

        samples = self.sample_page.get_samples()
        if not samples:
            QMessageBox.warning(self, "提示", "请先添加样本信息（样本配置页）")
            self.tab_widget.setCurrentIndex(1)
            return

        # 验证环境
        env = self.env_page.get_env_manager()
        if not env.env_exists():
            reply = QMessageBox.question(
                self, "环境未就绪",
                "Conda 环境尚未创建，是否现在创建并安装所有软件？",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self.tab_widget.setCurrentIndex(0)
                self.env_page._detect_conda()
                self.env_page._create_env()
                self.env_page._install_packages()
            else:
                return

        # 构建分析上下文
        ctx = AnalysisContext(
            work_dir=work_dir,
            species_prefix=self.param_page.get_species_prefix(),
            gene_prefix=self.param_page.get_gene_prefix(),
            threads=self.param_page.get_threads(),
            samples=samples,
        )

        extra_params = self.param_page.get_extra_params()
        active_steps = self.param_page.get_active_steps()

        # 开始运行
        self._log("\n" + "=" * 60)
        self._log("  开始执行转录组 de novo 组装流程")
        self._log(f"  工作目录: {work_dir}")
        self._log(f"  样本数量: {len(samples)}")
        self._log(f"  物种前缀: {ctx.species_prefix}")
        self._log("=" * 60)

        self._set_running_state(True)
        self.step_list.reset_all()
        self.progress_bar.setValue(0)

        # 启动后台线程
        self.worker = AnalysisWorker(env, ctx, extra_params, active_steps)
        self.worker.log_message.connect(self._on_log)
        self.worker.progress_updated.connect(self._on_progress)
        self.worker.step_changed.connect(self._on_step_change)
        self.worker.finished.connect(self._on_finished)
        self.worker.start()

    def _on_stop(self):
        if self.worker and self.worker.isRunning():
            reply = QMessageBox.question(
                self, "确认停止",
                "确定要停止当前运行的分析流程吗？\n已完成的步骤结果保留。",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self.worker.cancel()
                self._log("\n⚠ 用户请求停止流程...")
                self.statusBar().showMessage("正在停止...")

    def _set_running_state(self, running: bool):
        self.run_all_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        self.tab_widget.setEnabled(not running)
        if running:
            self.statusBar().showMessage("● 分析运行中...")

    @pyqtSlot(str)
    def _on_log(self, msg: str):
        self._log(msg)

    @pyqtSlot(int)
    def _on_progress(self, pct: int):
        self.progress_bar.setValue(pct)

    @pyqtSlot(str, str)
    def _on_step_change(self, step_id: str, status: str):
        self.step_list.set_step_status(step_id, status)

    def _on_finished(self):
        self._set_running_state(False)
        self.statusBar().showMessage("✓ 分析完成")
        self._log("\n✓ 流程执行完毕。")
        QMessageBox.information(self, "分析完成", "转录组 de novo 组装流程执行完毕！")

    # ---- 配置持久化 ----

    def _save_config(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "保存配置", "rnaseq_config.json", "JSON文件 (*.json)"
        )
        if path:
            # 同步 UI 到配置
            self.config.set("conda_env_name", self.env_page.env_name_edit.text())
            self.config.set("species_prefix", self.param_page.get_species_prefix())
            self.config.set("gene_prefix", self.param_page.get_gene_prefix())
            self.config.set("default_threads", self.param_page.get_threads())
            self.config.set("work_dir", self.param_page.get_work_dir())
            self.config.save(path)
            self._log(f"配置已保存到: {path}")

    def _load_config(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "加载配置", "", "JSON文件 (*.json)"
        )
        if path:
            self.config.load(path)
            self._log(f"配置已加载: {path}")
            # 刷新 UI
            self.env_page.conda_path_edit.setText(self.config.conda_path)
            self.env_page.env_name_edit.setText(self.config.conda_env_name)
            self.param_page.prefix_edit.setText(self.config.species_prefix)
            self.param_page.gene_prefix_edit.setText(self.config.gene_prefix)
            self.param_page.thread_spin.setValue(self.config.default_threads)

    def _load_window_state(self):
        """加载上次的窗口状态"""
        # 从配置文件恢复工作目录
        if self.config.work_dir:
            self.param_page.work_dir_edit.setText(self.config.work_dir)

    def _show_about(self):
        QMessageBox.about(
            self, "关于",
            "<h3>转录组分析软件 TVAS v" + __version__ + "</h3>"
            "<p>基于 conda 环境管理的一站式转录组测序数据分析工具</p>"
            "<p><b>三大分析模块:</b></p>"
            "<ol>"
            "<li><b>De Novo 组装</b> — FastQC → Fastp → Rcorrector → Trinity → CD-HIT → TransDecoder → Gffread</li>"
            "<li><b>序列比对</b> — HISAT2/STAR 比对、Samtools 处理、featureCounts 定量 <i>(开发中)</i></li>"
            "<li><b>差异表达分析</b> — DESeq2/edgeR 差异筛选、可视化、GO/KEGG 富集 <i>(开发中)</i></li>"
            "</ol>"
            "<p>适用平台: UOS / Debian / Ubuntu</p>"
        )
