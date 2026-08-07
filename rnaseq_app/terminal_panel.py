"""
转录组分析软件 - 环境终端面板

提供两种实现，对外接口统一：
  1. 真终端模式（优先）：基于 QTermWidget 的完整终端模拟器
     - 持久交互式 shell（cd / export / 变量状态会保留）
     - 支持彩色输出、光标控制、vim / top / less 等全屏交互程序
     - 启动时自动进入 conda 分析环境
     依赖: python3-pyqt5.qtermwidget（UOS: apt install python3-pyqt5.qtermwidget）

  2. 兼容模式（回退）：QPlainTextEdit + pty 单命令执行
     - 当 QTermWidget 不可用时（如 Windows 开发机）自动启用
     - 每条命令独立进程，支持 Tab 补全 / 命令历史 / 向运行中进程发送输入

主窗口只需调用 set_env_manager() 激活，无需关心具体实现。
"""

import os
import subprocess
from typing import List, Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QPlainTextEdit, QLineEdit, QPushButton, QTabWidget,
)
from PyQt5.QtCore import Qt, QThread, pyqtSlot, pyqtSignal
from PyQt5.QtGui import QTextCursor, QFont

from .env_manager import CondaEnvManager, get_app_data_dir


# ============================================================
# QTermWidget 可用性检测
# ============================================================
# UOS/Debian 安装 python3-pyqt5.qtermwidget 后即可 import；
# Windows 无现成包，自动回退到兼容模式。
try:
    from PyQt5.QTermWidget import QTermWidget as _QTermWidget
    _HAS_QTERM = True
except ImportError:
    _QTermWidget = None
    _HAS_QTERM = False


# conda 常用子命令（兼容模式 Tab 补全用）
CONDA_SUBCOMMANDS = [
    "activate", "create", "install", "update", "remove", "uninstall",
    "list", "search", "info", "config", "clean", "env", "run",
    "init", "build", "package", "verify", "compare", "convert",
    "debug", "develop", "help", "inspect", "render",
]

# 终端配色（与主窗口一致）
_TERM_BG = "#1e1e1e"
_TERM_FG = "#d4d4d4"
_TERM_PROMPT = "#27ae60"  # success 绿


# ============================================================
# 兼容模式：pty 单命令执行线程
# ============================================================

class TerminalWorker(QThread):
    """
    基于 pty 伪终端的实时终端工作线程（兼容模式用）。
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


# ============================================================
# 兼容模式：带历史 + Tab 补全的输入框
# ============================================================

class TermInput(QLineEdit):
    """带命令历史 + Tab 补全请求的终端输入框（兼容模式用）"""

    tab_pressed = pyqtSignal(str)  # 携带当前输入文本，由外部完成补全

    def __init__(self, parent=None):
        super().__init__(parent)
        self._history: List[str] = []
        self._idx = -1

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Tab:
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
            if len(self._history) > 200:
                self._history.pop(0)
        self._idx = len(self._history)
        self.clear()


# ============================================================
# 终端面板（统一入口）
# ============================================================

class TerminalPanel(QWidget):
    """
    环境终端面板。

    真终端模式（QTermWidget 可用时）:
      - 标签页分离「终端」与「命令日志」
      - 终端为持久交互式 shell，自动进入 conda 分析环境
      - 安装/卸载软件后点「刷新已安装版本」刷新主表格

    兼容模式（QTermWidget 不可用时）:
      - 单页 QPlainTextEdit + 输入行
      - 每条命令独立进程执行，Tab 补全 / 历史 / 交互输入

    对外信号:
      command_finished(bool)        —— 兼容模式单命令结束(成功与否)
      refresh_versions_requested()  —— 真终端模式用户请求刷新版本表
    """

    # 兼容模式：命令执行完成（成功与否），主窗口据此刷新版本表
    command_finished = pyqtSignal(bool)
    # 真终端模式：用户点击「刷新已安装版本」按钮
    refresh_versions_requested = pyqtSignal()

    # 是否真终端（类属性，供外部一次性判断）
    REAL_TERMINAL = _HAS_QTERM

    def __init__(self, parent=None):
        super().__init__(parent)
        self._env: Optional[CondaEnvManager] = None
        self._ready = False
        self._term_worker: Optional[TerminalWorker] = None  # 兼容模式
        self._qterm = None       # 真终端 QTermWidget 实例
        self._rcfile = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        if _HAS_QTERM:
            self._setup_real_terminal(layout)
        else:
            self._setup_fallback(layout)

    # ============================================================
    # 真终端模式
    # ============================================================

    def _setup_real_terminal(self, layout: QVBoxLayout):
        # 顶部标题 + 操作按钮
        header = QHBoxLayout()
        header.setSpacing(8)
        title = QLabel("环境终端（真终端 · 支持颜色 / vim / top 等交互程序）")
        title.setStyleSheet("color: #555; font-weight: bold;")
        header.addWidget(title)
        header.addStretch()

        self.restart_btn = QPushButton("重启终端")
        self.restart_btn.setToolTip("重启终端并重新进入分析环境")
        self.restart_btn.setCursor(Qt.PointingHandCursor)
        self.restart_btn.clicked.connect(self.restart)
        header.addWidget(self.restart_btn)

        self.refresh_btn = QPushButton("刷新已安装版本")
        self.refresh_btn.setToolTip("在终端中安装/卸载软件后，点击此处刷新版本表")
        self.refresh_btn.setCursor(Qt.PointingHandCursor)
        self.refresh_btn.clicked.connect(self.refresh_versions_requested.emit)
        header.addWidget(self.refresh_btn)

        layout.addLayout(header)

        # 终端 + 命令日志 标签页
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)

        self._qterm = self._create_qterm()
        self.tabs.addTab(self._qterm, "终端")

        # 命令日志页（供查看安装日志 / 最近命令输出 用，与终端分离避免互相覆盖）
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        self.log_view.setPlaceholderText(
            "命令日志区：安装/验证操作的完整输出会显示在这里。\n"
            "（终端里的命令不会记录到这里，请用终端自身的滚动历史）"
        )
        self.log_view.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: {_TERM_BG};
                color: {_TERM_FG};
                font-family: "Consolas", "DejaVu Sans Mono", monospace;
                font-size: 12px;
                border: none;
            }}
        """)
        self.tabs.addTab(self.log_view, "命令日志")

        layout.addWidget(self.tabs)

    def _create_qterm(self):
        """创建一个 QTermWidget 实例并应用统一样式（不启动 shell）"""
        # startnow=0 表示构造时不立即启动 shell，由我们配置后再启动
        try:
            term = _QTermWidget(0)
        except Exception:
            try:
                term = _QTermWidget(startnow=False)
            except Exception:
                term = _QTermWidget()

        # 颜色方案：Linux = 传统黑底彩字，与原有终端视觉一致
        try:
            term.setColorScheme("Linux")
        except Exception:
            pass
        # 滚动条靠右
        try:
            term.setScrollBarPosition(_QTermWidget.ScrollBarRight)
        except Exception:
            pass
        # 等宽字体
        try:
            font = QFont("DejaVu Sans Mono")
            font.setPointSize(11)
            term.setTerminalFont(font)
            term.setSize(80, 24)  # 初始行列数
        except Exception:
            pass
        return term

    def _start_qterm_shell(self):
        """启动 QTermWidget 的 shell（进入 conda 分析环境）"""
        if self._qterm is None:
            return
        env = self._env
        if env is None:
            # 无环境管理器：启动默认 shell
            try:
                self._qterm.startShellProgram()
            except Exception:
                pass
            return

        # 生成 rcfile：source conda.sh + conda activate 环境名
        self._rcfile = self._make_rcfile(env)

        try:
            self._qterm.setShellProgram("/bin/bash")
            self._qterm.setArgs(["--rcfile", self._rcfile, "-i"])
        except Exception:
            pass

        # 工作目录：优先 conda 环境路径，其次用户主目录
        env_path = env.get_env_path()
        cwd = env_path if env_path and os.path.isdir(env_path) else os.path.expanduser("~")
        try:
            self._qterm.setWorkingDirectory(cwd)
        except Exception:
            pass

        try:
            self._qterm.startShellProgram()
        except Exception:
            pass

    @staticmethod
    def _make_rcfile(env: CondaEnvManager) -> str:
        """
        生成终端启动 rcfile，让 bash 启动后自动激活 conda 分析环境。
        内容：source ~/.bashrc → source conda.sh → conda activate <env_name>
        """
        conda_exe = env.conda_exe
        # conda_exe 形如 .../miniconda/bin/conda，根目录是上两级
        conda_prefix = os.path.dirname(os.path.dirname(conda_exe))
        activate_sh = os.path.join(conda_prefix, "etc", "profile.d", "conda.sh")

        content = (
            "# TVAS 终端启动脚本（自动生成，勿手动编辑）\n"
            "[ -f ~/.bashrc ] && source ~/.bashrc 2>/dev/null\n"
            f'[ -f "{activate_sh}" ] && source "{activate_sh}"\n'
            f'conda activate {env.env_name} 2>/dev/null\n'
            'echo "[已进入分析环境: {0}]（exit 退出终端）"\n'
            .format(env.env_name)
        )
        rcfile = os.path.join(get_app_data_dir(), "term_rc.sh")
        os.makedirs(os.path.dirname(rcfile), exist_ok=True)
        try:
            with open(rcfile, "w", encoding="utf-8") as f:
                f.write(content)
        except OSError:
            pass
        return rcfile

    def restart(self):
        """重启终端（销毁旧 QTermWidget，创建新实例并启动 shell）"""
        if not _HAS_QTERM or self._qterm is None:
            return
        idx = self.tabs.indexOf(self._qterm)
        self.tabs.removeTab(idx)
        self._qterm.deleteLater()
        self._qterm = None

        self._qterm = self._create_qterm()
        self.tabs.insertTab(idx, self._qterm, "终端")
        self.tabs.setCurrentIndex(idx)

        if self._ready and self._env is not None:
            self._start_qterm_shell()
        else:
            try:
                self._qterm.startShellProgram()
            except Exception:
                pass

    def show_log_tab(self):
        """切换到命令日志页（真终端模式）"""
        if _HAS_QTERM and hasattr(self, "tabs"):
            self.tabs.setCurrentWidget(self.log_view)

    # ============================================================
    # 兼容模式
    # ============================================================

    def _setup_fallback(self, layout: QVBoxLayout):
        title = QLabel("环境终端（兼容模式 · 回车执行，上下键翻历史，Tab 补全）")
        title.setStyleSheet("color: #555; font-weight: bold;")
        layout.addWidget(title)

        # 视觉一体的终端容器（输出区 + 输入行在同一黑底框内）
        term_box = QFrame()
        term_box.setStyleSheet(f"""
            QFrame {{
                background-color: {_TERM_BG};
                border: 1px solid #333;
                border-radius: 6px;
            }}
        """)
        term_box_layout = QVBoxLayout(term_box)
        term_box_layout.setContentsMargins(8, 8, 8, 8)
        term_box_layout.setSpacing(4)

        # 兼容模式：终端输出与命令日志共用此视图（保持原有行为）
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(200)
        self.log_view.setPlaceholderText(
            "这是一个内置小终端，直接输入命令操作分析环境，例如：\n"
            "  conda list                            # 查看已安装软件包\n"
            "  conda install -c bioconda trinity=2.15  # 安装 Trinity\n"
            "  Trinity --version                     # 查看版本\n"
            "执行中可继续输入内容发送给命令（如 conda 询问 y/n 时输入 y 回车）"
        )
        self.log_view.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: transparent;
                color: {_TERM_FG};
                font-family: "Consolas", "DejaVu Sans Mono", monospace;
                font-size: 12px;
                border: none;
            }}
        """)
        term_box_layout.addWidget(self.log_view)

        term_input_row = QHBoxLayout()
        term_input_row.setSpacing(6)
        prompt = QLabel("$")
        prompt.setStyleSheet(
            f"color: {_TERM_PROMPT}; font-weight: bold; font-size: 14px;"
        )
        term_input_row.addWidget(prompt)
        self.term_input = TermInput()
        self.term_input.setPlaceholderText("输入命令后按回车执行，Tab 键自动补全...")
        self.term_input.returnPressed.connect(self._on_terminal_enter)
        self.term_input.tab_pressed.connect(self._on_terminal_tab)
        self.term_input.setEnabled(False)
        self.term_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: transparent;
                color: {_TERM_FG};
                font-family: "Consolas", "DejaVu Sans Mono", monospace;
                font-size: 12px;
                border: none;
                padding: 2px 0;
            }}
        """)
        term_input_row.addWidget(self.term_input, 1)
        term_box_layout.addLayout(term_input_row)

        layout.addWidget(term_box)

    # ---- 兼容模式：命令执行 ----

    def _term_bash_exe(self) -> str:
        """获取分析环境中的 bash 路径（等同 conda run）"""
        env = self._env
        if env is not None:
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
                    self.log_view.appendPlainText(f"  ↳ 已发送: {text.strip()}")
                else:
                    self.log_view.appendPlainText("  ↳ 发送失败（进程已结束）")
            self.term_input.clear()
            return

        cmd = text.strip()
        if not cmd:
            return

        # 回显命令（终端风格）
        self.log_view.appendPlainText(f"$ {cmd}")
        self.term_input.commit_command(cmd)
        self.term_input.setEnabled(False)

        worker = TerminalWorker(self._term_bash_exe(), cmd)
        worker.output.connect(self._on_terminal_output)
        worker.terminated.connect(self._on_terminal_done)
        self._term_worker = worker
        worker.start()

    @pyqtSlot(str)
    def _on_terminal_output(self, text: str):
        """实时输出追加到终端区"""
        self.log_view.appendPlainText(text)
        self.log_view.moveCursor(QTextCursor.End)

    @pyqtSlot(bool, str)
    def _on_terminal_done(self, ok, msg):
        self.log_view.appendPlainText(f"[进程结束 {msg}]")
        self.log_view.moveCursor(QTextCursor.End)
        self.term_input.setFocus()
        self._refresh_input_enabled()
        # 通知主窗口刷新版本表（兼容模式独有）
        self.command_finished.emit(ok)
        self._term_worker = None

    # ---- 兼容模式：Tab 自动补全 ----

    @pyqtSlot(str)
    def _on_terminal_tab(self, text: str):
        """Tab 补全：命令 / conda 子命令 / 文件路径"""
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
            common = os.path.commonprefix(candidates)
            if len(common) > len(token):
                self._apply_completion(before, after, token, common)
            else:
                self.log_view.appendPlainText("  候选: " + "  ".join(candidates))
                self.log_view.moveCursor(QTextCursor.End)

    def _get_tab_candidates(self, words: List[str], token: str) -> List[str]:
        candidates = []
        bash = self._term_bash_exe()

        if len(words) <= 1:
            candidates += self._run_compgen(bash, "c", token)
        else:
            if words[0] == "conda" and len(words) == 2:
                candidates += [
                    sub for sub in CONDA_SUBCOMMANDS if sub.startswith(token)
                ]
            candidates += self._run_compgen(bash, "f", token)
        return candidates

    @staticmethod
    def _run_compgen(bash: str, kind: str, token: str) -> List[str]:
        try:
            out = subprocess.run(
                [bash, "-c", f'compgen -{kind} -- "{token}" 2>/dev/null'],
                capture_output=True, text=True, timeout=5,
            )
            return [line for line in out.stdout.splitlines() if line]
        except Exception:
            return []

    def _apply_completion(self, before: str, after: str, token: str, replacement: str):
        head = before[:len(before) - len(token)]
        new_text = head + replacement + after
        self.term_input.setText(new_text)
        self.term_input.setCursorPosition(len(head) + len(replacement))

    # ============================================================
    # 公共接口（两种模式通用）
    # ============================================================

    def set_env_manager(self, env: Optional[CondaEnvManager], ready: bool):
        """
        设置/更新环境管理器与环境就绪状态。
        环境就绪时：真终端模式启动并进入 conda 环境；兼容模式启用输入框。
        """
        self._env = env
        self._ready = ready

        if _HAS_QTERM:
            # 真终端模式：环境就绪后启动进入分析环境的 shell
            if ready and env is not None:
                self._start_qterm_shell()
        else:
            self._refresh_input_enabled()

    def _refresh_input_enabled(self):
        """兼容模式：根据就绪/忙碌状态启用输入框"""
        if _HAS_QTERM:
            return
        busy = self._term_worker is not None and self._term_worker.isRunning()
        self.term_input.setEnabled(self._ready and not busy)

    def set_busy(self, busy: bool):
        """
        任务执行期间的忙碌状态（兼容模式禁用输入框）。
        真终端模式不受影响——用户可继续在终端操作。
        """
        if not _HAS_QTERM:
            self._refresh_input_enabled()

    def is_command_running(self) -> bool:
        """兼容模式：是否有命令正在运行"""
        if _HAS_QTERM:
            return False
        return self._term_worker is not None and self._term_worker.isRunning()

    def show_log(self, text: str):
        """显示日志文本并切换到日志页（覆盖式）"""
        self.log_view.setPlainText(text)
        if _HAS_QTERM:
            self.show_log_tab()

    def append_log(self, text: str):
        """追加日志文本并切换到日志页"""
        self.log_view.appendPlainText(text)
        self.log_view.moveCursor(QTextCursor.End)
        if _HAS_QTERM:
            self.show_log_tab()
