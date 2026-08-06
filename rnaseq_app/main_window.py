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
import json
from typing import List, Optional

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QPushButton, QLabel, QFrame, QListWidget, QListWidgetItem,
    QStackedWidget, QTextEdit, QProgressBar, QMessageBox, QFileDialog,
    QTabWidget, QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QCheckBox, QGroupBox,
    QFormLayout, QGridLayout, QSizePolicy, QAbstractItemView,
    QPlainTextEdit, QStatusBar, QMenuBar, QAction, QStyle,
)
from PyQt5.QtCore import Qt, QTimer, pyqtSlot, pyqtSignal
from PyQt5.QtGui import QFont, QColor, QTextCursor, QIcon, QPalette

from .config import ConfigManager
from .env_manager import (
    CondaEnvManager, PACKAGES,
    get_app_data_dir, get_local_conda_dir,
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
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        # ---- Conda 检测 ----
        group1 = QGroupBox("Conda 环境")
        group1.setStyleSheet(self._group_style())
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
        group2 = QGroupBox("软件包安装")
        group2.setStyleSheet(self._group_style())
        g2_layout = QVBoxLayout(group2)

        self.pkg_table = QTableWidget()
        self.pkg_table.setColumnCount(3)
        self.pkg_table.setHorizontalHeaderLabels(["软件包", "版本", "状态"])
        self.pkg_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.pkg_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.pkg_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.pkg_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.pkg_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.pkg_table.verticalHeader().setVisible(False)
        self.pkg_table.setAlternatingRowColors(True)
        self._populate_pkg_table()
        g2_layout.addWidget(self.pkg_table)

        pkg_btn_layout = QHBoxLayout()
        self.install_btn = QPushButton("安装全部软件包")
        self.install_btn.clicked.connect(self._install_packages)
        self.install_btn.setEnabled(False)
        self.install_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['primary_btn']};
                color: white;
                padding: 8px 24px;
                border-radius: 4px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {COLORS['primary_btn_hover']}; }}
            QPushButton:disabled {{ background-color: #bdc3c7; }}
        """)
        self.retry_btn = QPushButton("↻ 重装选中软件包")
        self.retry_btn.clicked.connect(self._retry_package)
        self.retry_btn.setEnabled(False)
        self.retry_btn.setToolTip("在表格中选中一行（可多选），点击后仅重装选中的软件包")
        self.retry_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['warning']};
                color: white;
                padding: 8px 20px;
                border-radius: 4px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background-color: #e67e22; }}
            QPushButton:disabled {{ background-color: #bdc3c7; }}
        """)
        self.verify_btn = QPushButton("验证安装")
        self.verify_btn.clicked.connect(self._verify_packages)
        self.verify_btn.setEnabled(False)
        pkg_btn_layout.addWidget(self.install_btn)
        pkg_btn_layout.addWidget(self.retry_btn)
        pkg_btn_layout.addWidget(self.verify_btn)
        pkg_btn_layout.addStretch()
        g2_layout.addLayout(pkg_btn_layout)

        # 双击某行也触发重装
        self.pkg_table.itemDoubleClicked.connect(self._retry_package)

        layout.addWidget(group2)
        layout.addStretch()

    def _group_style(self):
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

    def _populate_pkg_table(self):
        self.pkg_table.setRowCount(len(PACKAGES))
        for i, pkg in enumerate(PACKAGES):
            self.pkg_table.setItem(i, 0, QTableWidgetItem(pkg.name))
            ver = pkg.version if pkg.version else "latest"
            self.pkg_table.setItem(i, 1, QTableWidgetItem(ver))
            self.pkg_table.setItem(i, 2, QTableWidgetItem("未安装"))

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
                self.install_btn.setEnabled(True)
                self.retry_btn.setEnabled(True)
                self.verify_btn.setEnabled(True)
        elif info == "NEED_INSTALL":
            # 需要自动部署本地 Conda
            self.conda_path_edit.setText(os.path.join(get_local_conda_dir(), "bin", "conda"))
            self.conda_status_label.setText("未找到 Conda — 点击下方按钮自动部署（不影响系统）")
            self.conda_status_label.setStyleSheet(f"color: {COLORS['warning']}; font-weight: bold;")
            self.create_env_btn.setText("自动部署 Conda")
            self.create_env_btn.setEnabled(True)
            self.install_btn.setEnabled(False)
            self.verify_btn.setEnabled(False)
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
            self.install_btn.setEnabled(True)
            self.retry_btn.setEnabled(True)
            self.verify_btn.setEnabled(True)
        else:
            self.conda_status_label.setText(f"✗ 创建失败: {msg[:100]}")
            self.conda_status_label.setStyleSheet(f"color: {COLORS['error']};")
        self.create_env_btn.setEnabled(True)

    def _install_packages(self):
        env = self.get_env_manager()
        self.install_btn.setEnabled(False)
        self.verify_btn.setEnabled(False)

        for i in range(self.pkg_table.rowCount()):
            self.pkg_table.item(i, 2).setText("等待安装...")

        QApplication.processEvents()

        def progress_callback(current, total, msg):
            # 在主线程中更新UI
            pass

        results = env.install_all_packages(progress_callback)

        for i, (name, success, msg) in enumerate(results):
            status_text = "✓ 已安装" if success else f"✗ 失败"
            if i < self.pkg_table.rowCount():
                item = self.pkg_table.item(i, 2)
                item.setText(status_text)
                if success:
                    item.setForeground(QColor(COLORS["success"]))
                else:
                    item.setForeground(QColor(COLORS["error"]))

        self.install_btn.setEnabled(True)
        self.verify_btn.setEnabled(True)

        QMessageBox.information(
            self, "安装完成",
            f"软件包安装完成\n"
            f"成功: {sum(1 for _, s, _ in results if s)}/{len(results)}"
        )

    def _retry_package(self, item=None):
        """重装选中的软件包（支持表格选中多行 / 双击单行）"""
        # 双击触发时 item 为被双击的项；按钮触发时为 None
        if item is not None:
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

        env = self.get_env_manager()
        self.retry_btn.setEnabled(False)
        QApplication.processEvents()

        results = []
        for row in selected_rows:
            if row >= len(PACKAGES):
                continue
            pkg = PACKAGES[row]
            # 更新状态为安装中
            status_item = self.pkg_table.item(row, 2)
            if status_item:
                status_item.setText("安装中...")
                status_item.setForeground(QColor(COLORS["running"]))
            QApplication.processEvents()

            success, msg = env.install_package(pkg)
            results.append((pkg.name, success, msg))

            # 更新结果
            if status_item:
                status_item.setText("✓ 已安装" if success else "✗ 失败")
                status_item.setForeground(
                    QColor(COLORS["success"] if success else COLORS["error"])
                )
            QApplication.processEvents()

        self.retry_btn.setEnabled(True)
        self.verify_btn.setEnabled(True)

        ok_count = sum(1 for _, s, _ in results if s)
        QMessageBox.information(
            self, "重装完成",
            f"重装完成\n成功: {ok_count}/{len(results)}\n"
            + ("全部成功！" if ok_count == len(results)
               else "失败的软件包可再次选中后重装。")
        )

    def _verify_packages(self):
        env = self.get_env_manager()
        results = env.verify_all_packages()
        for i, (name, success, msg) in enumerate(results):
            if i < self.pkg_table.rowCount():
                item = self.pkg_table.item(i, 2)
                if success:
                    item.setText("✓ 已验证")
                    item.setForeground(QColor(COLORS["success"]))
                else:
                    item.setText("✗ 未通过")
                    item.setForeground(QColor(COLORS["error"]))
        QMessageBox.information(self, "验证完成", "软件包验证完成，请查看表格中的状态。")


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
        group.setStyleSheet(f"""
            QGroupBox {{
                font-weight: bold; border: 1px solid {COLORS['border']};
                border-radius: 8px; margin-top: 12px; padding-top: 20px;
                background-color: {COLORS['card_bg']};
            }}
            QGroupBox::title {{ subcontrol-origin: margin; left: 16px; padding: 0 8px; }}
        """)
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
        group1.setStyleSheet(self._group_style())
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
        group2.setStyleSheet(self._group_style())
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
        group3.setStyleSheet(self._group_style())
        g3 = QFormLayout(group3)

        self.tr_mem_edit = QLineEdit()
        self.tr_mem_edit.setText(self.config.trinity_params().get("max_memory", "50G"))
        g3.addRow("最大内存 (--max_memory):", self.tr_mem_edit)

        layout.addWidget(group3)

        # ---- CD-HIT 参数 ----
        group4 = QGroupBox("CD-HIT 去冗余参数")
        group4.setStyleSheet(self._group_style())
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
        group5.setStyleSheet(self._group_style())
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

    def _group_style(self):
        return f"""
            QGroupBox {{
                font-weight: bold; border: 1px solid {COLORS['border']};
                border-radius: 8px; margin-top: 12px; padding-top: 20px;
                background-color: {COLORS['card_bg']};
            }}
            QGroupBox::title {{ subcontrol-origin: margin; left: 16px; padding: 0 8px; }}
        """

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

        self.run_selected_btn = QPushButton("▶ 运行当前步骤")
        self.run_selected_btn.clicked.connect(self._on_run_all)
        self.run_selected_btn.setStyleSheet(self._btn_style(COLORS["primary_btn"]))
        control_layout.addWidget(self.run_selected_btn)

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
        self.run_selected_btn.setEnabled(not running)
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
