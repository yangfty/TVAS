"""
转录组分析软件 - 主界面

三大分析模块:
  [一、de novo 组装]  [二、序列比对]  [三、差异表达分析]
        ┃                    ┃                 ┃
        ┃                (开发中占位)     (开发中占位)
        ▼
┌─────────────────────────────────────────────┐
│  面包屑: 📍 一、de novo 组装 › 4. 任务运行    │
├─────────────────────────────────────────────┤
│  [1.环境设置] [2.样本配置] [3.参数配置] [4.任务运行] │
│                                             │
│  4.任务运行页:                               │
│  ┌─ 执行步骤选择 ──────────────────────────┐ │
│  │ ☑ 1.FastQC  (可选)        ◉ 运行中      │ │
│  │ ☑ 2.Fastp   (可选)        ○ 待运行      │ │
│  │ ☑ 3.Rcorrector (可选)     ○ 待运行      │ │
│  │ ☑ 4.Trinity ★必需         ○ 待运行      │ │
│  │ ...                                    │ │
│  └────────────────────────────────────────┘ │
│  ┌─ 运行日志 ──────────────────────────────┐ │
│  │ (实时输出)                              │ │
│  └────────────────────────────────────────┘ │
│  [进度条████████░░░░] [从头运行] [续跑] [停止]│
└─────────────────────────────────────────────┘
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
from .terminal_panel import launch_system_terminal
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


def _btn_style(bg: str, hover: str, padding: str = "8px 20px") -> str:
    """统一实心按钮样式"""
    return f"""
        QPushButton {{
            background-color: {bg};
            color: white;
            padding: {padding};
            border-radius: 4px;
            font-weight: bold;
            font-size: 13px;
        }}
        QPushButton:hover {{ background-color: {hover}; }}
        QPushButton:disabled {{ background-color: #bdc3c7; }}
    """


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


# ============================================================
# 模块导航栏
# ============================================================

class ModuleNavBar(QFrame):
    """顶部三大模块导航栏"""

    module_selected = pyqtSignal(int)

    # 模块定义: (名称, 状态, 说明)
    MODULES = [
        ("一、de novo 组装", "可用"),
        ("二、序列比对", "开发中"),
        ("三、差异表达分析", "开发中"),
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
        tip = QLabel("该模块正在开发中，将在后续版本中开放。当前版本请使用「一、de novo 组装」模块。")
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
                self.custom_install_btn,
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
            self.open_term_act, self.refresh_ver_act,
        ):
            w.setEnabled(ready)

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
        self.detect_btn.setStyleSheet(_btn_style("#7f8c8d", "#6c7a7a"))
        self.create_env_btn = QPushButton("创建环境")
        self.create_env_btn.clicked.connect(self._create_env)
        self.create_env_btn.setEnabled(False)
        self.create_env_btn.setStyleSheet(_btn_style(COLORS['primary_btn'], COLORS['primary_btn_hover']))
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
        self.install_btn.setStyleSheet(_btn_style(COLORS['primary_btn'], COLORS['primary_btn_hover'], "8px 24px"))
        self.verify_btn = QPushButton("✓ 验证安装")
        self.verify_btn.clicked.connect(self._verify_packages)
        self.verify_btn.setEnabled(False)
        self.verify_btn.setStyleSheet(_btn_style(COLORS['success'], "#219150"))

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

        self.more_menu.addSeparator()

        self.open_term_act = QAction("打开系统终端", self)
        self.open_term_act.triggered.connect(self._open_system_terminal)
        self.open_term_act.setToolTip("启动 UOS 系统终端，进入分析环境（conda activate + cd 工作目录）")
        self.open_term_act.setEnabled(False)
        self.more_menu.addAction(self.open_term_act)

        self.refresh_ver_act = QAction("刷新已安装版本", self)
        self.refresh_ver_act.triggered.connect(self._refresh_versions_from_env)
        self.refresh_ver_act.setToolTip("在终端中安装/卸载软件后，从环境读取版本刷新表格")
        self.refresh_ver_act.setEnabled(False)
        self.more_menu.addAction(self.refresh_ver_act)

        self.more_btn = QPushButton("更多操作 ▾")
        self.more_btn.setMenu(self.more_menu)
        self.more_btn.setEnabled(False)
        self.more_btn.setStyleSheet(_btn_style("#7f8c8d", "#6c7a7a"))

        pkg_btn_layout.addWidget(self.install_btn)
        pkg_btn_layout.addWidget(self.verify_btn)
        pkg_btn_layout.addWidget(self.more_btn)
        pkg_btn_layout.addStretch()
        g2_layout.addLayout(pkg_btn_layout)

        # 双击某行也触发重装
        self.pkg_table.itemDoubleClicked.connect(self._retry_package)

        layout.addWidget(group2)

        # 自定义安装（装额外软件包，如 salmon / hisat2）
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
        self.custom_install_btn.setStyleSheet(_btn_style("#7f8c8d", "#6c7a7a"))
        custom_row.addWidget(self.custom_install_btn)
        g2_layout.addLayout(custom_row)

        layout.addStretch()

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

        def task_fn():
            return env.install_custom_package(spec)

        self._run_env_task(task_fn, lambda ok, msg: self._on_custom_install_done(ok, msg, base_name))

    def _on_custom_install_done(self, ok, msg, base_name):
        env = self.get_env_manager()

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
            QMessageBox.warning(self, "安装失败", msg)

    def _open_system_terminal(self):
        """打开 UOS 系统终端，cd 到工作目录 + conda activate 进入分析环境"""
        env = self.get_env_manager()
        work_dir = ""
        win = self.window()
        if isinstance(win, MainWindow):
            work_dir = win.param_page.get_work_dir()
        ok, msg = launch_system_terminal(env, work_dir)
        if not ok:
            QMessageBox.warning(self, "打开终端失败", msg)
        else:
            QMessageBox.information(
                self, "已打开系统终端",
                f"已启动系统终端 ({msg})，进入分析环境"
                + (f"，工作目录: {work_dir}" if work_dir else "")
            )

    def _refresh_versions_from_env(self):
        """从环境中读取所有已安装包的版本，刷新表格（后台执行，不卡界面）"""
        env = self.get_env_manager()
        # 先在主线程收集包名（后台线程不能访问 GUI 控件）
        pkg_names = []
        for row in range(self.pkg_table.rowCount()):
            item = self.pkg_table.item(row, 0)
            pkg_names.append(item.text().strip() if item else "")
        self._set_env_busy(True, "正在刷新已安装版本")

        def task_fn():
            results = []
            for i, name in enumerate(pkg_names):
                ver = env.get_package_version(name) if name else ""
                results.append((i, ver))
            # 结果存到实例属性，on_done 从这里读
            # （EnvTaskWorker 会把第二个返回值 str() 化，不能直接传 list）
            self._refresh_results = results
            installed = sum(1 for _, v in results if v)
            return True, f"已安装 {installed}/{len(results)}"

        def on_done(ok, msg):
            results = getattr(self, "_refresh_results", [])
            if ok and results:
                for row, ver in results:
                    if ver:
                        ver_item = self.pkg_table.item(row, 1)
                        if ver_item:
                            ver_item.setText(ver)
                        status_item = self.pkg_table.item(row, 3)
                        if status_item and status_item.text() in ("未安装", "等待安装..."):
                            status_item.setText("✓ 已安装")
                            status_item.setForeground(QColor(COLORS["success"]))
            QMessageBox.information(self, "刷新完成", "已安装版本刷新完毕")

        self._run_env_task(task_fn, on_done)


# ============================================================
# 样本配置页
# ============================================================

class SampleConfigPage(QWidget):
    """样本配置页面（de novo 组装：选择 FASTQ 文件即自动配对 R1/R2）"""

    # R1/R2 文件名识别模式（顺序优先匹配）
    _R1_PATTERNS = ("_R1", "_1", "_r1", ".R1.")
    _R2_PATTERNS = ("_R2", "_2", "_r2", ".R2.")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        group = QGroupBox("样本配置")
        group.setStyleSheet(group_style())
        g_layout = QVBoxLayout(group)

        # 说明
        hint = QLabel(
            "选择待组装的 FASTQ 测序文件，系统将按文件名自动配对 R1 / R2。\n"
            "⚠ 暂时仅支持双端测序数据。"
        )
        hint.setStyleSheet("color: #666; font-size: 12px; margin-bottom: 8px;")
        hint.setWordWrap(True)
        g_layout.addWidget(hint)

        # 样本表格：3 列（样本名 | R1 路径 | R2 路径），样本名可编辑
        self.sample_table = QTableWidget()
        self.sample_table.setColumnCount(3)
        self.sample_table.setHorizontalHeaderLabels(
            ["样本名", "R1 FASTQ 路径", "R2 FASTQ 路径"]
        )
        self.sample_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.sample_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.sample_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.sample_table.verticalHeader().setVisible(False)
        self.sample_table.setAlternatingRowColors(True)
        self.sample_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        g_layout.addWidget(self.sample_table)

        # 操作按钮
        btn_layout = QHBoxLayout()
        self.import_files_btn = QPushButton("📂 选择 FASTQ 文件")
        self.import_files_btn.setToolTip("多选 FASTQ 文件，系统按文件名 _R1/_R2 自动配对填入下表")
        self.import_files_btn.clicked.connect(self._import_fastq_files)
        self.del_row_btn = QPushButton("− 删除选中")
        self.del_row_btn.clicked.connect(self._delete_row)
        self.clear_btn = QPushButton("清空")
        self.clear_btn.clicked.connect(self._clear_all)

        btn_layout.addWidget(self.import_files_btn)
        btn_layout.addWidget(self.del_row_btn)
        btn_layout.addWidget(self.clear_btn)
        btn_layout.addStretch()
        g_layout.addLayout(btn_layout)

        # 配对说明
        pair_hint = QLabel(
            "配对规则: 文件名包含 _R1/_1 匹配为 R1，_R2/_2 匹配为 R2；"
            "样本名取 R1 文件名去掉 _R1 后缀（可手动修改）。"
        )
        pair_hint.setStyleSheet("color: #7f8c8d; font-size: 11px; margin-top: 6px;")
        pair_hint.setWordWrap(True)
        g_layout.addWidget(pair_hint)

        layout.addWidget(group)
        layout.addStretch()

    # ---- 文件选择与自动配对 ----

    def _import_fastq_files(self):
        """多选 FASTQ 文件，自动按文件名配对 R1/R2 填入表格"""
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择 FASTQ 测序文件（可多选）", "",
            "FASTQ 文件 (*.fastq *.fq *.fastq.gz *.fq.gz);;所有文件 (*)"
        )
        if not paths:
            return

        # 按文件名 base 配对
        pairs = {}  # base -> {"r1": path, "r2": path}
        for p in paths:
            fname = os.path.basename(p)
            base, role = self._detect_role(fname)
            entry = pairs.setdefault(base, {"r1": "", "r2": "", "unpaired": []})
            if role == "r1" and not entry["r1"]:
                entry["r1"] = p
            elif role == "r2" and not entry["r2"]:
                entry["r2"] = p
            else:
                entry["unpaired"].append(p)

        # 填入表格
        added = 0
        unpaired = []
        for base, entry in pairs.items():
            if entry["r1"] and entry["r2"]:
                self._add_paired_row(base, entry["r1"], entry["r2"])
                added += 1
            else:
                unpaired.extend(entry["unpaired"])

        msg = f"已自动配对 {added} 个样本。"
        if unpaired:
            msg += (
                f"\n\n以下 {len(unpaired)} 个文件未能配对（缺少对应的 R1/R2），已忽略：\n  "
                + "\n  ".join(os.path.basename(p) for p in unpaired[:10])
            )
            if len(unpaired) > 10:
                msg += f"\n  ...等共 {len(unpaired)} 个"
            msg += "\n\n请确认文件名包含 _R1/_R2（或 _1/_2）后缀。"
        QMessageBox.information(self, "导入完成", msg)

    def _detect_role(self, fname: str):
        """从文件名识别样本 base 名和 R1/R2 角色，返回 (base, 'r1'|'r2'|'')"""
        for pat in self._R1_PATTERNS:
            idx = fname.find(pat)
            if idx > 0:
                return fname[:idx], "r1"
        for pat in self._R2_PATTERNS:
            idx = fname.find(pat)
            if idx > 0:
                return fname[:idx], "r2"
        # 无法识别时用完整文件名（去扩展名）作为 base，标记为未知
        return os.path.splitext(fname)[0], ""

    def _add_paired_row(self, base: str, r1: str, r2: str):
        row = self.sample_table.rowCount()
        self.sample_table.insertRow(row)
        name_item = QTableWidgetItem(base)
        name_item.setToolTip("样本名（可手动修改），用于组装结果命名")
        r1_item = QTableWidgetItem(r1)
        r1_item.setToolTip(r1)
        r1_item.setFlags(r1_item.flags() & ~Qt.ItemIsEditable)
        r2_item = QTableWidgetItem(r2)
        r2_item.setToolTip(r2)
        r2_item.setFlags(r2_item.flags() & ~Qt.ItemIsEditable)
        self.sample_table.setItem(row, 0, name_item)
        self.sample_table.setItem(row, 1, r1_item)
        self.sample_table.setItem(row, 2, r2_item)

    # ---- 表格操作 ----

    def _delete_row(self):
        rows = set(idx.row() for idx in self.sample_table.selectedIndexes())
        for row in sorted(rows, reverse=True):
            self.sample_table.removeRow(row)

    def _clear_all(self):
        self.sample_table.setRowCount(0)

    def get_samples(self) -> List[SampleInfo]:
        """获取所有样本信息（de novo 组装：group 与 replicate 均取样本名）"""
        samples = []
        for row in range(self.sample_table.rowCount()):
            name_item = self.sample_table.item(row, 0)
            r1 = self.sample_table.item(row, 1)
            r2 = self.sample_table.item(row, 2)
            if name_item and r1 and r2:
                name = name_item.text().strip()
                r1_path = r1.text().strip()
                r2_path = r2.text().strip()
                if name and r1_path and r2_path:
                    # de novo 组装不需要真实分组，group/replicate 均用样本名
                    samples.append(SampleInfo(
                        group=name, replicate=name,
                        r1_path=r1_path, r2_path=r2_path
                    ))
        return samples

    def has_samples(self) -> bool:
        return len(self.get_samples()) > 0


# ============================================================
# 参数配置页
# ============================================================

class _NoWheelSpinBox(QSpinBox):
    """滚动页面时滚轮不会误改数值的 QSpinBox（仅当控件获得焦点时才响应滚轮）"""
    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class _NoWheelDoubleSpinBox(QDoubleSpinBox):
    """滚动页面时滚轮不会误改数值的 QDoubleSpinBox（仅当控件获得焦点时才响应滚轮）"""
    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class ParamConfigPage(QWidget):
    """参数配置页面"""

    def __init__(self, config: ConfigManager, parent=None):
        super().__init__(parent)
        self.config = config
        self._setup_ui()

    # 各参数默认值（供「恢复默认参数」使用）
    _DEFAULTS = {
        "species_prefix": "Hvi",
        "gene_prefix": "Uni",
        "threads": 4,
        "fastp_quality": 20,
        "fastp_min_length": 50,
        "trinity_max_memory_num": 50,   # 数值部分（G 单位固定显示在控件后方）
        "cd_hit_identity": 0.80,
    }

    def _setup_ui(self):
        # 外层：滚动区域，窗口较小时也能完整浏览所有参数
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

        # ---- 顶部操作条：恢复默认参数 ----
        top_bar = QHBoxLayout()
        top_bar.addStretch()
        self.restore_default_btn = QPushButton("↺ 恢复默认参数")
        self.restore_default_btn.setToolTip("将所有参数恢复为默认值")
        self.restore_default_btn.setStyleSheet(_btn_style("#7f8c8d", "#6c7a7a"))
        self.restore_default_btn.clicked.connect(self._restore_defaults)
        top_bar.addWidget(self.restore_default_btn)
        layout.addLayout(top_bar)

        # ---- 基本参数 ----
        group1 = QGroupBox("基本参数")
        group1.setStyleSheet(group_style())
        g1 = QFormLayout(group1)
        g1.setLabelAlignment(Qt.AlignRight)
        g1.setFormAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        g1.setSpacing(12)
        g1.setContentsMargins(16, 22, 16, 16)

        self.work_dir_edit = QLineEdit()
        self.work_dir_edit.setPlaceholderText("选择分析输出目录...")
        self.work_dir_edit.setToolTip("所有分析结果（FASTQC报告、清洗后的reads、Trinity组装结果等）将输出到此目录下的子文件夹")
        browse_btn = QPushButton("浏览...")
        browse_btn.clicked.connect(self._browse_work_dir)
        dir_layout = QHBoxLayout()
        dir_layout.addWidget(self.work_dir_edit)
        dir_layout.addWidget(browse_btn)
        work_dir_label = QLabel("工作目录:")
        work_dir_label.setToolTip("分析结果将输出到此目录下的各子文件夹")
        g1.addRow(work_dir_label, dir_layout)
        work_dir_hint = QLabel(
            "分析结果将输出到此目录下的各子文件夹"
            "（01_fastqc_out / 02_fastp_clean / 04_trinity_out 等）"
        )
        work_dir_hint.setStyleSheet("color: #7f8c8d; font-size: 12px;")
        work_dir_hint.setWordWrap(True)
        g1.addRow("", work_dir_hint)

        self.prefix_edit = QLineEdit()
        self.prefix_edit.setText(self.config.species_prefix)
        self.prefix_edit.setPlaceholderText("如 Hvi")
        self.prefix_edit.setToolTip("组装后的转录本序列命名前缀，如 Hvi_TRINITY_DN1000_c0_g1")
        prefix_field = self._line_row(self.prefix_edit, f"默认 {self._DEFAULTS['species_prefix']}")
        g1.addRow("物种前缀:", prefix_field)

        self.gene_prefix_edit = QLineEdit()
        self.gene_prefix_edit.setText(self.config.gene_prefix)
        self.gene_prefix_edit.setPlaceholderText("如 Uni")
        self.gene_prefix_edit.setToolTip("基因命名前缀，用于最终的重命名步骤统一基因ID格式")
        gene_field = self._line_row(self.gene_prefix_edit, f"默认 {self._DEFAULTS['gene_prefix']}")
        g1.addRow("基因前缀:", gene_field)

        self.thread_spin = _NoWheelSpinBox()
        self.thread_spin.setRange(1, 128)
        self.thread_spin.setValue(self.config.default_threads)
        self.thread_spin.setToolTip("分配给各步骤的CPU线程数，建议不超过物理核心数；Trinity/CD-HIT等会用到")
        g1.addRow("CPU 线程:", self._spin_row(self.thread_spin, self._DEFAULTS["threads"]))

        layout.addWidget(group1)

        # ---- Fastp 参数 ----
        group2 = QGroupBox("Fastp 过滤参数")
        group2.setStyleSheet(group_style())
        g2 = QFormLayout(group2)
        g2.setLabelAlignment(Qt.AlignRight)
        g2.setSpacing(12)
        g2.setContentsMargins(16, 22, 16, 16)

        fp = self.config.fastp_params()
        self.fp_q_spin = _NoWheelSpinBox()
        self.fp_q_spin.setRange(10, 40)
        self.fp_q_spin.setValue(fp.get("quality_threshold", 20))
        self.fp_q_spin.setToolTip("Phred质量阈值，低于此值的碱基将被截断（-q 参数）。值越高过滤越严格")
        g2.addRow("质量阈值 (-q):", self._spin_row(self.fp_q_spin, self._DEFAULTS["fastp_quality"]))

        self.fp_l_spin = _NoWheelSpinBox()
        self.fp_l_spin.setRange(20, 200)
        self.fp_l_spin.setValue(fp.get("min_length", 50))
        self.fp_l_spin.setToolTip("过滤后reads的最小保留长度（-l 参数），短于此值的reads将被丢弃")
        g2.addRow("最小长度 (-l):", self._spin_row(self.fp_l_spin, self._DEFAULTS["fastp_min_length"]))

        layout.addWidget(group2)

        # ---- Trinity 参数 ----
        group3 = QGroupBox("Trinity 组装参数")
        group3.setStyleSheet(group_style())
        g3 = QFormLayout(group3)
        g3.setLabelAlignment(Qt.AlignRight)
        g3.setSpacing(12)
        g3.setContentsMargins(16, 22, 16, 16)

        self.tr_mem_spin = _NoWheelSpinBox()
        self.tr_mem_spin.setRange(1, 999)
        # 从配置中解析数值（如 "50G" → 50）
        mem_str = self.config.trinity_params().get("max_memory", "50G")
        try:
            mem_num = int("".join(c for c in str(mem_str) if c.isdigit()))
        except Exception:
            mem_num = 50
        self.tr_mem_spin.setValue(mem_num)
        self.tr_mem_spin.setToolTip("Trinity组装可用的最大内存（--max_memory），单位固定为 G。建议设为物理内存的80%")
        # SpinBox + 固定 G 后缀
        mem_field = QHBoxLayout()
        mem_field.setSpacing(4)
        mem_field.addWidget(self.tr_mem_spin)
        mem_unit = QLabel("G")
        mem_unit.setStyleSheet("color: #2c3e50; font-size: 13px; font-weight: bold;")
        mem_field.addWidget(mem_unit)
        mem_hint = QLabel(f"默认 {self._DEFAULTS['trinity_max_memory_num']}G")
        mem_hint.setStyleSheet("color: #95a5a6; font-size: 12px;")
        mem_field.addWidget(mem_hint)
        mem_field.addStretch()
        g3.addRow("最大内存 (--max_memory):", mem_field)
        tr_hint = QLabel("建议设为物理内存的 80%（如 64G 内存填 50）")
        tr_hint.setStyleSheet("color: #7f8c8d; font-size: 12px;")
        tr_hint.setWordWrap(True)
        g3.addRow("", tr_hint)

        layout.addWidget(group3)

        # ---- CD-HIT 参数 ----
        group4 = QGroupBox("CD-HIT 去冗余参数")
        group4.setStyleSheet(group_style())
        g4 = QFormLayout(group4)
        g4.setLabelAlignment(Qt.AlignRight)
        g4.setSpacing(12)
        g4.setContentsMargins(16, 22, 16, 16)

        ch = self.config.cd_hit_params()
        self.ch_identity_spin = _NoWheelDoubleSpinBox()
        self.ch_identity_spin.setRange(0.70, 1.0)
        self.ch_identity_spin.setSingleStep(0.05)
        self.ch_identity_spin.setValue(ch.get("identity_threshold", 0.80))
        self.ch_identity_spin.setDecimals(2)
        self.ch_identity_spin.setToolTip("序列相似性阈值（-c）。0.80 表示80%相似度的转录本聚为一类去冗余，值越高保留越多")
        g4.addRow("相似性阈值 (-c):", self._spin_row(self.ch_identity_spin, f"{self._DEFAULTS['cd_hit_identity']:.2f}"))
        ch_hint = QLabel("范围 0.70~1.00。0.80=较宽松去冗余，0.95=较严格保留更多转录本")
        ch_hint.setStyleSheet("color: #7f8c8d; font-size: 12px;")
        ch_hint.setWordWrap(True)
        g4.addRow("", ch_hint)

        layout.addWidget(group4)
        layout.addStretch()

    # ---- 行布局辅助：spinbox + 默认值提示 ----

    def _spin_row(self, spin, default_text) -> QHBoxLayout:
        """数值控件 + 默认值提示，缩短编辑条宽度，布局更美观"""
        spin.setFixedWidth(100)
        hint = QLabel(f"默认 {default_text}")
        hint.setStyleSheet("color: #95a5a6; font-size: 12px;")
        field = QHBoxLayout()
        field.setSpacing(8)
        field.addWidget(spin)
        field.addWidget(hint)
        field.addStretch()
        return field

    def _line_row(self, line_edit, default_text) -> QHBoxLayout:
        """文本控件 + 默认值提示"""
        line_edit.setMaximumWidth(200)
        hint = QLabel(default_text)
        hint.setStyleSheet("color: #95a5a6; font-size: 12px;")
        field = QHBoxLayout()
        field.setSpacing(8)
        field.addWidget(line_edit)
        field.addWidget(hint)
        field.addStretch()
        return field

    def _restore_defaults(self):
        """将所有参数恢复为默认值"""
        d = self._DEFAULTS
        self.prefix_edit.setText(d["species_prefix"])
        self.gene_prefix_edit.setText(d["gene_prefix"])
        self.thread_spin.setValue(d["threads"])
        self.fp_q_spin.setValue(d["fastp_quality"])
        self.fp_l_spin.setValue(d["fastp_min_length"])
        self.tr_mem_spin.setValue(d["trinity_max_memory_num"])
        self.ch_identity_spin.setValue(d["cd_hit_identity"])
        self._log_parent("已恢复默认参数")

    def _log_parent(self, msg: str):
        """向主窗口日志输出（运行页日志）"""
        win = self.window()
        if hasattr(win, "_log"):
            win._log(msg)

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

    def get_extra_params(self) -> dict:
        return {
            "fastp_quality": self.fp_q_spin.value(),
            "fastp_min_length": self.fp_l_spin.value(),
            "trinity_max_memory": f"{self.tr_mem_spin.value()}G",
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

        # 面包屑导航栏：清晰显示当前所处的大步骤（模块）与小步骤（Tab）
        self.breadcrumb_label = QLabel()
        self.breadcrumb_label.setStyleSheet(f"""
            QLabel {{
                background-color: {COLORS['card_bg']};
                color: #2c3e50;
                font-size: 14px;
                font-weight: bold;
                padding: 8px 16px;
                border-bottom: 1px solid {COLORS['border']};
            }}
        """)
        denovo_layout.addWidget(self.breadcrumb_label)

        # Tab 页面（移除左侧步骤导航栏，步骤选择整合到「4. 任务运行」页）
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

        # ---- 第 4 个 Tab: 任务运行（执行步骤选择 + 运行日志 + 进度/按钮） ----
        run_page = QWidget()
        run_layout = QVBoxLayout(run_page)
        run_layout.setContentsMargins(12, 12, 12, 12)
        run_layout.setSpacing(10)

        # ---- 步骤选择与状态显示（整合：运行前为复选框，运行后显示状态） ----
        step_group = QGroupBox("执行步骤选择")
        step_group.setStyleSheet(group_style())
        sg_layout = QVBoxLayout(step_group)
        sg_layout.setSpacing(4)
        sg_layout.setContentsMargins(16, 22, 16, 16)

        step_hint = QLabel(
            "勾选需要运行的步骤（标 ★ 为必需步骤，不可取消）。\n"
            "运行开始后，此区域将实时显示每步的执行状态。"
        )
        step_hint.setStyleSheet("color: #7f8c8d; font-size: 12px; margin-bottom: 4px;")
        step_hint.setWordWrap(True)
        sg_layout.addWidget(step_hint)

        self.step_checkboxes = {}
        self.step_status_labels = {}
        for i, step in enumerate(PIPELINE_STEPS):
            row = QHBoxLayout()
            row.setSpacing(8)
            # 复选框
            required = step.get("required", True)
            label_text = f"{i+1}. {step['name']}"
            if not required:
                label_text += "  (可选)"
            cb = QCheckBox(label_text)
            cb.setChecked(True)
            if required:
                cb.setEnabled(False)  # 必需步骤不可取消勾选
                cb.setToolTip(f"必需步骤，不可跳过。{step['description']}")
            else:
                cb.setToolTip(f"可选步骤，可跳过。{step['description']}")
            self.step_checkboxes[step["id"]] = cb
            row.addWidget(cb)
            # 状态标签（运行时显示 ○/◉/✓/✗/−）
            status_lbl = QLabel("")
            status_lbl.setFixedWidth(30)
            status_lbl.setAlignment(Qt.AlignCenter)
            status_lbl.setStyleSheet("font-size: 14px; font-weight: bold;")
            self.step_status_labels[step["id"]] = status_lbl
            row.addWidget(status_lbl)
            row.addStretch()
            sg_layout.addLayout(row)
        run_layout.addWidget(step_group)

        # ---- 运行日志 ----
        log_group = QGroupBox("运行日志")
        log_group.setStyleSheet(group_style())
        log_layout = QVBoxLayout(log_group)
        log_layout.setContentsMargins(8, 18, 8, 8)
        log_layout.setSpacing(4)
        log_header = QHBoxLayout()
        log_label = QLabel("实时输出（分析运行中的各环节日志）")
        log_label.setStyleSheet("color: #7f8c8d; font-size: 12px;")
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
        run_layout.addWidget(log_group, 1)

        # ---- 进度条与运行按钮 ----
        control_layout = QHBoxLayout()
        control_layout.setContentsMargins(0, 0, 0, 0)
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

        self.run_all_btn = QPushButton("▶ 从头运行")
        self.run_all_btn.clicked.connect(lambda: self._on_run_all(resume=False))
        self.run_all_btn.setStyleSheet(self._btn_style(COLORS["primary_btn"]))
        self.run_all_btn.setToolTip("从头运行所有勾选的步骤（已有输出会被覆盖）")
        control_layout.addWidget(self.run_all_btn)

        self.resume_btn = QPushButton("⚡ 续跑")
        self.resume_btn.clicked.connect(lambda: self._on_run_all(resume=True))
        self.resume_btn.setStyleSheet(self._btn_style("#27ae60"))
        self.resume_btn.setToolTip("续跑模式：自动跳过输出已存在的步骤，从上次中断处继续")
        control_layout.addWidget(self.resume_btn)

        self.stop_btn = QPushButton("■ 停止")
        self.stop_btn.clicked.connect(self._on_stop)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet(self._btn_style(COLORS["danger_btn"]))
        control_layout.addWidget(self.stop_btn)
        run_layout.addLayout(control_layout)

        self.tab_widget.addTab(run_page, "4. 任务运行")

        # Tab 切换时更新面包屑
        self.tab_widget.currentChanged.connect(self._update_breadcrumb)

        denovo_layout.addWidget(self.tab_widget, 1)

        self.module_stack.addWidget(denovo_widget)

        # 初始化面包屑
        self._update_breadcrumb(0)

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
        module_names = ["de novo 组装", "序列比对", "差异表达分析"]
        if idx == 0:
            self.statusBar().showMessage("就绪 | de novo 组装模块")
        else:
            self.statusBar().showMessage(
                f"{module_names[idx]} 模块开发中，将在后续版本开放"
            )
        self._update_breadcrumb(self.tab_widget.currentIndex() if idx == 0 else -1)

    def _update_breadcrumb(self, tab_idx: int):
        """更新顶部面包屑，清晰显示当前大步骤（模块）与小步骤（Tab）"""
        module_idx = self.module_stack.currentIndex()
        module_names = ["一、de novo 组装", "二、序列比对", "三、差异表达分析"]
        if module_idx != 0:
            # 非 de novo 模块：仅显示模块名
            self.breadcrumb_label.setText(f"📍 {module_names[module_idx]}")
            return
        tab_labels = [
            "1. 环境设置", "2. 样本配置", "3. 参数配置", "4. 任务运行",
        ]
        sub = tab_labels[tab_idx] if 0 <= tab_idx < len(tab_labels) else ""
        self.breadcrumb_label.setText(f"📍 {module_names[0]}  ›  {sub}")

    # ---- 运行流程 ----

    def _on_run_all(self, resume: bool = False):
        """运行全部流程

        Args:
            resume: True=续跑模式（跳过输出已存在的步骤），False=从头运行
        """
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
        active_steps = [sid for sid, cb in self.step_checkboxes.items() if cb.isChecked()]

        # 续跑模式提示
        if resume:
            self._log("\n" + "=" * 60)
            self._log("  ⚡ 续跑模式：将自动跳过输出已存在的步骤")
            self._log(f"  工作目录: {work_dir}")
            self._log("  每步输出保存在独立子文件夹（01_fastqc_out, 02_fastp_clean 等）")
            self._log("  已完成的步骤会保留结果，从中断处继续")
            self._log("=" * 60)
        else:
            self._log("\n" + "=" * 60)
            self._log("  开始执行转录组 de novo 组装流程（从头运行）")
            self._log(f"  工作目录: {work_dir}")
            self._log(f"  样本数量: {len(samples)}")
            self._log(f"  物种前缀: {ctx.species_prefix}")
            self._log(f"  执行步骤: {len(active_steps)} 个")
            self._log("  每步输出保存在独立子文件夹，便于管理和断点续跑")
            self._log("=" * 60)

        self._set_running_state(True)
        self._reset_step_statuses()
        self.progress_bar.setValue(0)
        # 切换到「4. 任务运行」页，方便查看实时日志
        self.tab_widget.setCurrentIndex(3)

        # 启动后台线程
        self.worker = AnalysisWorker(env, ctx, extra_params, active_steps,
                                     resume_mode=resume)
        self.worker.log_message.connect(self._on_log)
        self.worker.progress_updated.connect(self._on_progress)
        self.worker.step_changed.connect(self._on_step_change)
        self.worker.finished.connect(self._on_finished)
        self.worker.start()

    def _on_stop(self):
        """停止当前运行的分析流程"""
        if self.worker and self.worker.isRunning():
            reply = QMessageBox.question(
                self, "确认停止",
                "确定要停止当前运行的分析流程吗？\n\n"
                "• 已完成的步骤结果保留在各自子文件夹中\n"
                "• 停止后可点击「⚡ 续跑」从中断处继续\n"
                "• 每步输出保存在独立子文件夹（01_fastqc_out 等），不会丢失",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self.worker.cancel()
                self._log("\n⚠ 用户请求停止流程，正在终止当前命令...")
                self.statusBar().showMessage("正在停止...")

    def _set_running_state(self, running: bool):
        """设置运行/停止状态下的控件可用性"""
        self.run_all_btn.setEnabled(not running)
        self.resume_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        # 运行时禁用各配置页和步骤复选框，但保留「4. 任务运行」页可操作（查看日志、停止）
        for page in (self.env_page, self.sample_page, self.param_page):
            page.setEnabled(not running)
        for cb in self.step_checkboxes.values():
            # 必需步骤本来就 disabled，可选步骤运行时也禁用
            if cb.isEnabled():
                cb.setEnabled(not running)
        if running:
            self.statusBar().showMessage("● 分析运行中...")

    def _reset_step_statuses(self):
        """重置所有步骤状态标签为空"""
        for lbl in self.step_status_labels.values():
            lbl.setText("")
            lbl.setStyleSheet("font-size: 14px; font-weight: bold;")

    @pyqtSlot(str)
    def _on_log(self, msg: str):
        self._log(msg)

    @pyqtSlot(int)
    def _on_progress(self, pct: int):
        self.progress_bar.setValue(pct)

    @pyqtSlot(str, str)
    def _on_step_change(self, step_id: str, status: str):
        """更新步骤状态标签（整合在执行步骤选择区域）"""
        icons = {
            StepStatus.PENDING.value: ("○", COLORS["pending"]),
            StepStatus.RUNNING.value: ("◉", COLORS["running"]),
            StepStatus.SUCCESS.value: ("✓", COLORS["success"]),
            StepStatus.FAILED.value: ("✗", COLORS["error"]),
            StepStatus.SKIPPED.value: ("−", COLORS["skipped"]),
        }
        if step_id in self.step_status_labels:
            icon, color = icons.get(status, ("○", COLORS["pending"]))
            lbl = self.step_status_labels[step_id]
            lbl.setText(icon)
            lbl.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {color};")

    def _on_finished(self):
        self._set_running_state(False)
        self.statusBar().showMessage("✓ 分析完成")
        self._log("\n✓ 流程执行完毕。")
        # 恢复可选步骤复选框为可用
        for step_id, cb in self.step_checkboxes.items():
            step = next((s for s in PIPELINE_STEPS if s["id"] == step_id), None)
            if step and not step.get("required", True):
                cb.setEnabled(True)
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
