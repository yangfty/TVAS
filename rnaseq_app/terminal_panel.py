"""
转录组分析软件 - 环境终端面板

提供「打开系统终端」入口 + 命令日志区。
点击按钮启动 UOS 系统终端（deepin-terminal / gnome-terminal / xterm），
自动 cd 到工作目录并 conda activate 进入分析环境。

放弃自建终端（QTermWidget / pty 单命令）方案——系统终端原生体验更好、
无卡顿、无命令执行后误触发版本刷新等问题。
"""

import os
import shutil
import subprocess
from typing import Tuple

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QPlainTextEdit,
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QTextCursor

from .env_manager import CondaEnvManager, get_app_data_dir


_TERM_BG = "#1e1e1e"
_TERM_FG = "#d4d4d4"


# ============================================================
# 启动 UOS 系统终端
# ============================================================

def launch_system_terminal(env_manager: CondaEnvManager,
                           work_dir: str = "") -> Tuple[bool, str]:
    """
    启动 UOS 系统终端，自动 cd 到工作目录 + conda activate 进入分析环境。

    返回: (是否成功, 消息)
    依赖系统终端: deepin-terminal / gnome-terminal / konsole / xterm 任一。
    """
    conda_exe = env_manager.conda_exe
    # conda_exe 形如 .../miniconda/bin/conda，根目录是上两级
    conda_prefix = os.path.dirname(os.path.dirname(conda_exe))
    activate_sh = os.path.join(conda_prefix, "etc", "profile.d", "conda.sh")
    env_name = env_manager.env_name

    cwd = work_dir if work_dir and os.path.isdir(work_dir) else os.path.expanduser("~")

    # 生成启动脚本: source conda.sh + activate + cd
    script = (
        "# TVAS 系统终端启动脚本（自动生成，勿手动编辑）\n"
        "[ -f ~/.bashrc ] && source ~/.bashrc 2>/dev/null\n"
        f'[ -f "{activate_sh}" ] && source "{activate_sh}"\n'
        f"conda activate {env_name} 2>/dev/null\n"
        f'cd "{cwd}"\n'
        f'echo "[已进入分析环境: {env_name}]  工作目录: {cwd}"\n'
        f'echo "（exit 退出终端）"\n'
    )
    script_path = os.path.join(get_app_data_dir(), "open_terminal.sh")
    os.makedirs(os.path.dirname(script_path), exist_ok=True)
    try:
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(script)
        os.chmod(script_path, 0o755)
    except OSError as e:
        return False, f"生成启动脚本失败: {e}"

    # 按优先级查找系统终端（UOS 默认 deepin-terminal）
    # 用 bash -c 'source script; exec bash' 让脚本执行后保持交互式终端
    inner = f'source "{script_path}"; exec bash'
    candidates = [
        ["deepin-terminal", "-w", cwd, "-e", "bash", "-c", inner],
        ["gnome-terminal", "--", "bash", "-c", inner],
        ["konsole", "-e", "bash", "-c", inner],
        ["xfce4-terminal", "-x", "bash", "-c", inner],
        ["mate-terminal", "--", "bash", "-c", inner],
        ["xterm", "-e", "bash", "-c", inner],
    ]

    for cmd in candidates:
        exe = cmd[0]
        if shutil.which(exe):
            try:
                # start_new_session: 终端独立运行，不随本程序退出而关闭
                subprocess.Popen(cmd, cwd=cwd, start_new_session=True)
                return True, exe
            except Exception as e:
                return False, f"{exe} 启动失败: {e}"

    return False, "未找到系统终端（请安装 deepin-terminal / gnome-terminal / xterm）"


# ============================================================
# 终端面板（系统终端入口 + 命令日志区）
# ============================================================

class TerminalPanel(QWidget):
    """
    环境终端入口 + 命令日志区。

    - 顶部: 「打开系统终端」按钮（启动 UOS 原生终端，cd 工作目录 + conda activate）
    - 下方: 命令日志区（显示安装/验证操作的完整输出）

    对外信号:
      open_terminal_requested()    —— 请求打开系统终端（由主窗口协调 env + work_dir）
      refresh_versions_requested() —— 用户点击「刷新已安装版本」
    """

    open_terminal_requested = pyqtSignal()
    refresh_versions_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ready = False
        self._busy = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # ---- 顶部: 标题 + 按钮 ----
        header = QHBoxLayout()
        header.setSpacing(8)
        title = QLabel("环境终端")
        title.setStyleSheet("color: #555; font-weight: bold;")
        header.addWidget(title)
        header.addStretch()

        self.open_term_btn = QPushButton("打开系统终端")
        self.open_term_btn.setToolTip(
            "启动 UOS 系统终端，自动进入分析环境（conda activate）并 cd 到工作目录"
        )
        self.open_term_btn.setCursor(Qt.PointingHandCursor)
        self.open_term_btn.setEnabled(False)
        self.open_term_btn.clicked.connect(self.open_terminal_requested.emit)
        header.addWidget(self.open_term_btn)

        self.refresh_btn = QPushButton("刷新已安装版本")
        self.refresh_btn.setToolTip("在终端中安装/卸载软件后，点击此处刷新版本表")
        self.refresh_btn.setCursor(Qt.PointingHandCursor)
        self.refresh_btn.setEnabled(False)
        self.refresh_btn.clicked.connect(self.refresh_versions_requested.emit)
        header.addWidget(self.refresh_btn)

        layout.addLayout(header)

        hint = QLabel(
            "点击「打开系统终端」在独立窗口中操作分析环境"
            "（支持颜色 / vim / top 等全部交互功能）。"
            "安装/验证操作的输出记录在下方命令日志区。"
        )
        hint.setStyleSheet("color: #888; font-size: 11px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # ---- 命令日志区 ----
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(200)
        self.log_view.setMaximumBlockCount(5000)
        self.log_view.setPlaceholderText(
            "命令日志区：安装/验证操作的完整输出会显示在这里。\n"
            "终端里的命令不会记录到这里（系统终端有自己的滚动历史）。"
        )
        self.log_view.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: {_TERM_BG};
                color: {_TERM_FG};
                font-family: "Consolas", "DejaVu Sans Mono", monospace;
                font-size: 12px;
                border: 1px solid #333;
                border-radius: 6px;
            }}
        """)
        layout.addWidget(self.log_view)

    # ============================================================
    # 公共接口
    # ============================================================

    def set_env_ready(self, ready: bool):
        """环境就绪状态（启用/禁用「打开系统终端」按钮）"""
        self._ready = ready
        self._refresh_buttons()

    def set_busy(self, busy: bool):
        """任务执行期间禁用按钮"""
        self._busy = busy
        self._refresh_buttons()

    def _refresh_buttons(self):
        enabled = self._ready and not self._busy
        self.open_term_btn.setEnabled(enabled)
        self.refresh_btn.setEnabled(enabled)

    def show_log(self, text: str):
        """显示日志文本（覆盖式）"""
        self.log_view.setPlainText(text)

    def append_log(self, text: str):
        """追加日志文本"""
        self.log_view.appendPlainText(text)
        self.log_view.moveCursor(QTextCursor.End)
