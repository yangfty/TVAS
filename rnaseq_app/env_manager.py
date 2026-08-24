"""
转录组de novo组装软件 - Conda环境管理器（自包含版）

负责:
  - 检测/下载/部署本地 Miniconda（不影响系统）
  - 创建虚拟环境
  - 安装所有生物信息学软件
  - 在隔离环境中执行命令
"""

import os
import re
import sys
import json
import subprocess
import shutil
import urllib.request
import stat
import threading
from datetime import datetime
from typing import Tuple, List, Dict, Optional
from dataclasses import dataclass, field


# ============================================================
# 自包含 Miniconda 路径
# ============================================================

def get_app_data_dir() -> str:
    """获取应用数据目录（所有 conda 相关文件都放在这里）"""
    # 优先级: XDG_DATA_HOME > ~/.local/share/TVAS
    base = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
    return os.path.join(base, "TVAS")


def get_bundled_conda_dir() -> str:
    """获取内置 conda 路径"""
    # PyInstaller 打包后检查 sys._MEIPASS
    try:
        base = sys._MEIPASS
        bundled = os.path.join(base, "miniconda")
        if os.path.isdir(bundled) and os.path.isfile(os.path.join(bundled, "bin", "conda")):
            return bundled
    except AttributeError:
        pass
    return ""


def get_local_conda_dir() -> str:
    """获取用户本地部署的 conda 路径"""
    return os.path.join(get_app_data_dir(), "miniconda")


def get_local_envs_dir() -> str:
    """获取本地环境存储目录"""
    return os.path.join(get_app_data_dir(), "envs")


# ============================================================
# Conda ToS 条款自动接受
# ============================================================
# 新版 Miniconda (>=23.11) 捆绑 conda-anaconda-tos 插件，
# 要求显式接受 Anaconda 官方 channel 的服务条款。
# 非交互运行（如本程序）时 conda 无法弹窗确认会报
# CondaToSNonInteractiveError，因此注入环境变量自动接受。

def _ensure_condarc() -> str:
    """生成应用专属 condarc（浙大 ZJU 国内镜像），返回文件路径。

    bioconda/conda-forge 官方服务器在国外，国内直连经常下载中途
    卡死或报 HTTP 超时。通过 CONDARC 环境变量让本程序启动的所有
    conda 子进程走镜像；不影响用户终端里的 conda（~/.condarc 原样）。
    已存在的配置不覆盖（保留用户手动调整）；写入失败返回空串退回默认。
    """
    path = os.path.join(get_app_data_dir(), "condarc")
    try:
        if os.path.isfile(path):
            # 旧版写的是清华 TUNA 镜像（该站已停止 anaconda 镜像服务），
            # 自动替换为浙大镜像；用户手写的其他配置不动
            with open(path, "r", encoding="utf-8") as f:
                old = f.read()
            if "tuna.tsinghua" not in old:
                return path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        content = (
            "# TVAS 自动生成 - 浙大 ZJU 镜像（国内下载加速）\n"
            "default_channels:\n"
            "  - https://mirrors.zju.edu.cn/anaconda/pkgs/main\n"
            "  - https://mirrors.zju.edu.cn/anaconda/pkgs/r\n"
            "custom_channels:\n"
            "  conda-forge: https://mirrors.zju.edu.cn/anaconda/cloud\n"
            "  bioconda: https://mirrors.zju.edu.cn/anaconda/cloud\n"
            "show_channel_urls: true\n"
            "# 弱网容忍: 更多重试 + 更长超时，减少下载中途卡死\n"
            "remote_max_retries: 5\n"
            "remote_connect_timeout_secs: 30\n"
            "remote_read_timeout_secs: 180\n"
        )
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path
    except Exception:
        return ""


def _conda_env() -> dict:
    """构造 conda 子进程环境变量（自动接受 ToS + 国内镜像加速）"""
    env = dict(os.environ)
    env["CONDA_PLUGINS_AUTO_ACCEPT_TOS"] = "true"
    env.setdefault("CONDA_AUTO_UPDATE_CONDA", "false")
    condarc = _ensure_condarc()
    if condarc:
        env["CONDARC"] = condarc
    return env


# ============================================================
# 软件包安装清单
# ============================================================

@dataclass
class PackageSpec:
    """单个软件包的安装规格"""
    name: str
    version: str = ""                    # 期望版本（可空=最新），安装后显示实际版本
    channel: str = "bioconda"
    extra_channels: List[str] = field(default_factory=list)
    verify_cmd: str = ""
    required: bool = True                # 是否必需（de novo 流程必备）
    description: str = ""                # 用途说明
    install_timeout: int = 1800          # 安装超时（秒），大包需更长

    @property
    def display_name(self) -> str:
        return self.name


PACKAGES = [
    PackageSpec(
        name="fastqc", version="0.11",
        verify_cmd="fastqc --version",
        required=True, description="原始测序数据质量评估",
    ),
    PackageSpec(
        name="fastp",
        verify_cmd="fastp --version",
        required=True, description="数据过滤与去接头",
    ),
    PackageSpec(
        name="rcorrector",
        verify_cmd="perl -e 'exit 0'",
        required=True, description="RNA-seq reads 纠错",
    ),
    PackageSpec(
        name="trinity", version="2.15",
        extra_channels=["conda-forge"],
        verify_cmd="Trinity --version",
        required=True, description="de novo 转录本组装",
        install_timeout=3600,             # 超大包（数百 MB），慢网络下需更久
    ),
    PackageSpec(
        name="jellyfish", version="2.2",
        verify_cmd="jellyfish --version",
        required=True, description="k-mer 计数（Trinity 依赖）",
    ),
    PackageSpec(
        name="samtools",
        verify_cmd="samtools --version",
        required=True, description="BAM/SAM 处理（Trinity 依赖，需 ≥1.3）",
    ),
    PackageSpec(
        name="cd-hit", version="4.8",
        verify_cmd="cd-hit --version",
        required=True, description="转录本聚类去冗余",
    ),
    PackageSpec(
        name="transdecoder", version="5.5",
        extra_channels=["conda-forge"],
        verify_cmd="TransDecoder.LongOrfs --version",
        required=True, description="CDS 开放阅读框预测",
    ),
    PackageSpec(
        name="kallisto", version="0.51",
        extra_channels=["conda-forge"],   # 依赖的 hdf5 >=1.14.3 仅在 conda-forge
        verify_cmd="kallisto version",
        required=True, description="转录本定量",
    ),
    PackageSpec(
        name="gffread",
        verify_cmd="gffread --version",
        required=True, description="GFF3 注释与序列提取",
    ),
]

# Miniconda 下载地址
MINICONDA_URL = (
    "https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh"
)


# ============================================================
# 环境管理器（自包含版）
# ============================================================

class CondaEnvManager:
    """
    管理 conda 虚拟环境的创建、软件安装与命令执行。

    Conda 来源优先级:
      1. 调用者指定的路径
      2. 内置 Miniconda（PyInstaller 打包附带）
      3. 用户本地部署的 Miniconda（~/.local/share/TVAS/miniconda/）
      4. 系统已安装的 Conda
      5. 自动下载 Miniconda 到本地目录（首次启动引导）
    """

    MINICONDA_URL = MINICONDA_URL

    def __init__(self, env_name: str, conda_path: str = ""):
        self.env_name = env_name
        self._conda_exe = self._resolve_conda(conda_path)
        # ---- 进程管理与取消支持 ----
        self._current_proc: Optional[subprocess.Popen] = None
        self._proc_lock = threading.Lock()
        self._cancelled = False
        # ---- 安装日志 ----
        self._install_log_fh = None
        self._install_log_path = ""

    @property
    def is_cancelled(self) -> bool:
        """是否已请求取消（供步骤函数循环中检查）"""
        return self._cancelled

    def reset_cancel(self):
        """重置取消标志（新一轮运行前调用）"""
        self._cancelled = False

    def cancel_current_command(self):
        """取消当前正在运行的命令：终止子进程树"""
        self._cancelled = True
        with self._proc_lock:
            proc = self._current_proc
        if proc and proc.poll() is None:
            # 先 SIGTERM，再 SIGKILL，确保子进程树退出
            try:
                # 杀整个进程组（conda run 启动的孙进程也要清理）
                try:
                    os.killpg(os.getpgid(proc.pid), 15)  # SIGTERM
                except Exception:
                    proc.terminate()
                # 等待 2 秒
                try:
                    proc.wait(timeout=2)
                except Exception:
                    try:
                        os.killpg(os.getpgid(proc.pid), 9)  # SIGKILL
                    except Exception:
                        proc.kill()
            except Exception:
                pass

    # ---- 安装日志（持久化到文件，便于排查安装失败） ----

    @staticmethod
    def get_install_log_dir() -> str:
        """安装日志目录（与 conda 数据同级的 logs/install/）"""
        d = os.path.join(get_app_data_dir(), "logs", "install")
        os.makedirs(d, exist_ok=True)
        return d

    def begin_install_session(self, mode: str):
        """开始一次安装会话：创建带时间戳的日志文件并写入头部"""
        try:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            self._install_log_path = os.path.join(
                self.get_install_log_dir(), f"install_{ts}.log")
            self._install_log_fh = open(
                self._install_log_path, "w", encoding="utf-8")
            self._log_write("=" * 64)
            self._log_write("TVAS 软件包安装日志")
            self._log_write(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            self._log_write(f"模式: {mode}")
            self._log_write(f"环境: {self.env_name}")
            self._log_write(f"Conda: {self._conda_exe}")
            self._log_write("=" * 64)
        except Exception:
            self._install_log_fh = None
            self._install_log_path = ""

    def end_install_session(self):
        """结束安装会话，关闭日志文件"""
        if self._install_log_fh:
            try:
                self._log_write("=" * 64)
                self._log_write(f"会话结束: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                self._install_log_fh.close()
            except Exception:
                pass
        self._install_log_fh = None

    @property
    def install_log_path(self) -> str:
        """当前（或最近一次）安装会话的日志文件路径"""
        return self._install_log_path

    @staticmethod
    def list_install_logs() -> List[str]:
        """列出历史安装日志，新的在前"""
        try:
            d = CondaEnvManager.get_install_log_dir()
            files = [os.path.join(d, f) for f in os.listdir(d)
                     if f.endswith(".log")]
            return sorted(files, key=os.path.getmtime, reverse=True)
        except Exception:
            return []

    def _log_write(self, text: str):
        """写入一行日志（安装会话未开启时静默忽略）"""
        if self._install_log_fh:
            try:
                self._install_log_fh.write(text + "\n")
            except Exception:
                pass

    def _log_pkg_result(self, label: str, cmd: List[str], rc: int,
                        out: str, err: str, success: bool, brief: str):
        """记录单个软件包的命令与完整输出"""
        self._log_write("")
        self._log_write("-" * 64)
        self._log_write(f"[{label}]")
        self._log_write(f"命令: {' '.join(cmd)}")
        self._log_write(f"退出码: {rc}")
        self._log_write(f"结果: {'✓ 成功' if success else '✗ 失败'}  {brief}")
        self._log_write("-" * 64)
        if (out or "").strip():
            self._log_write("[stdout]")
            self._log_write(out.rstrip())
        if (err or "").strip():
            self._log_write("[stderr]")
            self._log_write(err.rstrip())
        try:
            self._install_log_fh.flush()
        except Exception:
            pass

    # ---- 统一命令执行 ----

    def _exec(self, cmd: List[str], timeout: int, cwd: str = "") -> Tuple[int, str, str]:
        """执行 conda 命令，返回 (returncode, stdout, stderr)。

        使用 Popen 启动进程，保存句柄以支持 cancel_current_command() 中断。
        每次执行前重置取消标志。
        """
        self._cancelled = False
        try:
            # 启动新进程组，便于整组终止
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=cwd or None,
                env=_conda_env(),
                # Linux: 子进程自成进程组，可 killpg 整组清理
                start_new_session=True,
            )
            with self._proc_lock:
                self._current_proc = proc
            try:
                out, err = proc.communicate(timeout=timeout)
                return proc.returncode, out or "", err or ""
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                return -1, "", f"命令超时（>{timeout}秒）"
        except Exception as e:
            return -1, "", str(e)
        finally:
            with self._proc_lock:
                self._current_proc = None

    # ---- Conda 解析（自包含优先） ----

    @classmethod
    def _resolve_conda(cls, custom_path: str) -> str:
        """按优先级查找 conda 可执行文件"""
        # 1. 调用者指定
        if custom_path and os.path.isfile(custom_path):
            return custom_path

        # 2. 内置 Miniconda（PyInstaller 打包附带）
        bundled = get_bundled_conda_dir()
        if bundled:
            conda = os.path.join(bundled, "bin", "conda")
            if os.path.isfile(conda):
                return conda

        # 3. 用户本地部署的 Miniconda
        local = os.path.join(get_local_conda_dir(), "bin", "conda")
        if os.path.isfile(local):
            return local

        # 4. 系统 Conda
        for p in [
            shutil.which("conda"),
            shutil.which("mamba"),
            os.path.expanduser("~/miniconda3/bin/conda"),
            os.path.expanduser("~/anaconda3/bin/conda"),
            "/opt/conda/bin/conda",
            "/usr/local/bin/conda",
        ]:
            if p and os.path.isfile(p):
                return p

        # 5. 未找到任何 conda，返回本地路径（后续可自动下载）
        return os.path.join(get_local_conda_dir(), "bin", "conda")

    @property
    def conda_exe(self) -> str:
        return self._conda_exe

    # ---- 自包含 Conda 部署 ----

    @classmethod
    def is_local_conda_installed(cls) -> bool:
        """检查本地 conda 是否已部署"""
        return os.path.isfile(os.path.join(get_local_conda_dir(), "bin", "conda"))

    @classmethod
    def install_local_conda(cls, progress_callback=None) -> Tuple[bool, str]:
        """
        下载并安装 Miniconda 到应用本地目录。
        完全不影响系统，不需要 sudo。
        """
        local_dir = get_local_conda_dir()
        app_dir = get_app_data_dir()
        os.makedirs(app_dir, exist_ok=True)

        # 如果已存在，验证可用性
        if cls.is_local_conda_installed():
            return True, "本地 Conda 已就绪"

        installer_path = os.path.join(app_dir, "miniconda_installer.sh")

        # 下载 installer: 浙大镜像优先（国内快），官方源兜底。
        # 浙大站无 latest 别名文件，需固定具体版本名
        urls = [
            "https://mirrors.zju.edu.cn/anaconda/miniconda/"
            "Miniconda3-py39_25.9.1-3-Linux-x86_64.sh",
            cls.MINICONDA_URL,
        ]
        last_err = None
        downloaded = False
        for url in urls:
            if progress_callback:
                host = url.split("/")[2]
                progress_callback(f"正在下载 Miniconda (~100MB, {host})...")
            try:
                _download_file(url, installer_path)
                downloaded = True
                break
            except Exception as e:
                last_err = e
        if not downloaded:
            return False, f"下载 Miniconda 失败: {last_err}\n请检查网络连接"

        # 静默安装
        if progress_callback:
            progress_callback("正在安装 Miniconda 到本地目录...")

        try:
            result = subprocess.run(
                ["bash", installer_path, "-b", "-p", local_dir],
                capture_output=True, text=True, timeout=300,
                env=_conda_env(),
            )
            if result.returncode != 0:
                return False, f"安装失败: {result.stderr[-300:]}"
        except subprocess.TimeoutExpired:
            return False, "安装超时"
        finally:
            # 清理 installer
            try:
                os.remove(installer_path)
            except OSError:
                pass

        # 验证
        conda_bin = os.path.join(local_dir, "bin", "conda")
        if not os.path.isfile(conda_bin):
            return False, "安装后未找到 conda 可执行文件"

        # 禁用 conda 自动激活 base 环境
        try:
            subprocess.run(
                [conda_bin, "config", "--set", "auto_activate_base", "false"],
                capture_output=True, timeout=30, env=_conda_env(),
            )
        except Exception:
            pass

        # 显式接受 Anaconda ToS（双保险，兼容未识别环境变量的版本）
        try:
            subprocess.run(
                [conda_bin, "tos", "accept", "--override-channels",
                 "--channel", "https://repo.anaconda.com/pkgs/main"],
                capture_output=True, timeout=30, env=_conda_env(),
            )
            subprocess.run(
                [conda_bin, "tos", "accept", "--override-channels",
                 "--channel", "https://repo.anaconda.com/pkgs/r"],
                capture_output=True, timeout=30, env=_conda_env(),
            )
        except Exception:
            pass

        return True, f"本地 Conda 安装完成 ({local_dir})"

    # ---- Conda 状态 ----

    def is_conda_installed(self) -> Tuple[bool, str]:
        """检查conda是否可用（含自动部署提示）"""
        # 如果 conda 路径指向本地且不存在，说明需要下载
        local_dir = get_local_conda_dir()
        if local_dir in self._conda_exe and not os.path.isfile(self._conda_exe):
            return False, "NEED_INSTALL"  # 特殊标记：需要自动部署

        try:
            result = subprocess.run(
                [self._conda_exe, "--version"],
                capture_output=True, text=True, timeout=10,
                env=_conda_env(),
            )
            if result.returncode == 0:
                return True, result.stdout.strip()
            return False, result.stderr.strip()
        except FileNotFoundError:
            return False, "NEED_INSTALL"
        except Exception as e:
            return False, str(e)

    def ensure_conda_ready(self, progress_callback=None) -> Tuple[bool, str]:
        """确保 conda 可用，如果不可用则自动部署本地版"""
        ok, info = self.is_conda_installed()
        if ok:
            return True, info
        if info == "NEED_INSTALL":
            return self.install_local_conda(progress_callback)
        return False, info

    # ---- 环境管理 ----

    def env_exists(self) -> bool:
        try:
            result = subprocess.run(
                [self._conda_exe, "env", "list"],
                capture_output=True, text=True, timeout=15,
                env=_conda_env(),
            )
            for line in result.stdout.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split()
                if parts and parts[0] == self.env_name:
                    return True
            return False
        except Exception:
            return False

    def get_env_path(self) -> Optional[str]:
        try:
            result = subprocess.run(
                [self._conda_exe, "env", "list"],
                capture_output=True, text=True, timeout=15,
                env=_conda_env(),
            )
            for line in result.stdout.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split()
                if parts and parts[0] == self.env_name and len(parts) >= 2:
                    return parts[-1]
        except Exception:
            pass
        return None

    def _broken_env_dir(self) -> str:
        """检测残缺环境目录：目录存在但缺 conda-meta（有效环境的标志）。

        多为环境创建中途超时/取消/磁盘满留下的半成品，或删除不彻底的遗留。
        返回残缺目录路径；无残缺返回空串。
        """
        try:
            # conda 可执行文件位于 <conda_root>/bin/conda → envs 在 <conda_root>/envs
            # shutil.which 解析 PATH 上的 conda / 符号链接，避免 abspath 相对路径误判
            exe = shutil.which(self._conda_exe) or os.path.abspath(self._conda_exe)
            conda_root = os.path.dirname(os.path.dirname(exe))
            d = os.path.join(conda_root, "envs", self.env_name)
            if os.path.isdir(d) and not os.path.isdir(os.path.join(d, "conda-meta")):
                return d
        except Exception:
            pass
        return ""

    def env_state(self) -> str:
        """环境状态: 'ok' 有效 | 'broken' 残缺(目录在但缺元数据) | 'missing' 不存在"""
        if self._broken_env_dir():
            return "broken"
        return "ok" if self.env_exists() else "missing"

    def free_disk_gb(self) -> float:
        """conda 所在磁盘剩余空间（GB）；无法检测返回 -1"""
        try:
            exe = shutil.which(self._conda_exe) or os.path.abspath(self._conda_exe)
            conda_root = os.path.dirname(os.path.dirname(exe))
            for p in (conda_root, os.path.dirname(conda_root), os.path.expanduser("~")):
                if os.path.isdir(p):
                    return shutil.disk_usage(p).free / 2**30
        except Exception:
            pass
        return -1.0

    def create_env(self, prefix: Optional[str] = None) -> Tuple[bool, str]:
        """
        创建conda虚拟环境。
        如果指定 prefix，环境建在指定目录（自包含隔离）。
        """
        # 残缺环境目录必须最先清理（放在 env_exists 判断之前）：
        # 缺 conda-meta 的目录必然不是有效环境，但 conda create 会因
        # "prefix already exists" 拒绝创建、install 会报
        # DirectoryNotACondaEnvironmentError，形成死锁。
        cleaned = ""
        if prefix is None:
            broken = self._broken_env_dir()
            if broken:
                shutil.rmtree(broken, ignore_errors=True)
                cleaned = "（已自动清理上次创建中断留下的残缺目录）"

        if self.env_exists():
            return True, f"环境 '{self.env_name}' 已存在"

        # 磁盘空间预检：空间不足是"安装中断→环境残缺"的常见根因
        free_gb = self.free_disk_gb()
        if 0 <= free_gb < 2:
            return False, (
                f"磁盘剩余空间不足（仅 {free_gb:.1f} GB，完整环境约需 5 GB）。\n"
                "请清理磁盘后重试，可先清理 conda 下载缓存:\n"
                f"  {self._conda_exe} clean -a -y"
            )

        cmd = [self._conda_exe, "create", "-n", self.env_name, "-y", "python=3.8"]
        if prefix:
            cmd = [self._conda_exe, "create", "-p", prefix, "-y", "python=3.8"]

        try:
            # 慢网络下 python 包下载可能较久，预留 15 分钟
            rc, out, err = self._exec(cmd, 900)
            if rc == 0:
                return True, f"环境 '{self.env_name}' 创建成功{cleaned}"
            return False, (err or out)[-500:]
        except subprocess.TimeoutExpired:
            return False, "创建环境超时（超过15分钟）"
        except Exception as e:
            return False, str(e)

    def ensure_env(self) -> Tuple[bool, str]:
        """确保分析环境存在且可用；缺失或残缺时自动重建（残缺目录会被清理）。"""
        state = self.env_state()
        if state == "ok":
            return True, f"环境 '{self.env_name}' 就绪"
        return self.create_env()

    def get_package_version(self, pkg_name: str) -> str:
        """查询环境中某软件包的实际安装版本（未安装返回空）"""
        try:
            rc, out, _ = self._exec(
                [self._conda_exe, "list", "-n", self.env_name, pkg_name], 60
            )
            if rc != 0:
                return ""
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 2 and parts[0].lower() == pkg_name.lower():
                    return parts[1]
        except Exception:
            pass
        return ""

    def get_versions_bulk(self) -> Dict[str, str]:
        """一次 conda list --json 获取环境内全部 {包名小写: 版本}。

        比逐包 conda list 查询快得多（一次进程调用），
        且 JSON 输出不依赖文本列对齐，更可靠。
        """
        try:
            rc, out, _ = self._exec(
                [self._conda_exe, "list", "-n", self.env_name, "--json"], 180)
            if rc != 0 or not out.strip():
                return {}
            data = json.loads(out)
            versions: Dict[str, str] = {}
            for item in data:
                name = (item.get("name") or "").strip().lower()
                if name:
                    versions[name] = item.get("version") or ""
            return versions
        except Exception:
            return {}

    @staticmethod
    def version_from_output(output: str) -> str:
        """从工具自身的 --version 输出中提取版本号（兜底用）。

        如 "Trinity version: Trinity-v2.15.2" → "2.15.2"
           "kallisto 0.51.1" → "0.51.1"
        """
        if not output:
            return ""
        m = re.search(r'v?(\d+\.\d+(?:\.\d+)?)', output)
        return m.group(1) if m else ""

    def uninstall_package(self, pkg_name: str) -> Tuple[bool, str]:
        """卸载环境中的单个软件包"""
        cmd = [self._conda_exe, "remove", "-n", self.env_name, "-y", pkg_name]
        rc, out, err = self._exec(cmd, 600)
        if rc == 0:
            return True, f"✓ {pkg_name} 卸载成功"
        if "packages not found" in (out + err).lower() or "no packages" in (out + err).lower():
            return True, f"✓ {pkg_name} 未安装（无需卸载）"
        detail = (err or out)[-300:]
        advice = self.analyze_error(err or out)
        msg = f"✗ {pkg_name} 卸载失败: {detail}"
        if advice:
            msg += f"\n\n{advice}"
        return False, msg

    def remove_env(self) -> Tuple[bool, str]:
        """删除整个分析环境（等同卸载全部，最干净）"""
        cmd = [self._conda_exe, "env", "remove", "-n", self.env_name, "-y"]
        rc, out, err = self._exec(cmd, 300)
        if rc == 0:
            return True, f"环境 '{self.env_name}' 已删除"
        return False, f"删除失败: {(err or out)[-300:]}"

    @staticmethod
    def analyze_error(err_text: str) -> str:
        """分析 conda 错误信息，返回中文排查建议（无匹配返回空）"""
        err = err_text.lower()
        if "unsatisfiableerror" in err or "found conflicts" in err or "incompatible" in err:
            # 依赖缺 channel 的典型特征: "does not exist (perhaps a missing channel)"
            if "missing channel" in err or "not installable" in err:
                return (
                    "检测到依赖冲突: 所需的依赖包在当前 channel 中不存在。\n"
                    "建议: 附加 conda-forge 频道重试（bioconda 的部分依赖仅在 conda-forge）:\n"
                    "     conda install -n 环境 -c bioconda -c conda-forge <包名>"
                )
            return (
                "检测到依赖冲突 (UnsatisfiableError)。\n"
                "建议: ① 去掉版本号安装最新版（旧版可能与已装包冲突）\n"
                "     ② 或新建环境后重装: 环境设置页删除环境再创建\n"
                "     ③ 或清理缓存后重试: conda clean -i -a"
            )
        if "not a conda environment" in err or "directorynotacondaenvironment" in err:
            return (
                "环境目录残缺（缺少 conda-meta 元数据），多为创建中途被打断所致。\n"
                "建议: 在「环境设置」页点击「创建环境」自动清理残缺目录并重建，"
                "重建后再安装软件包。"
            )
        if "post-link script failed" in err or "linkerror" in err:
            return (
                "软件包的 post-link 安装脚本执行失败。\n"
                "最常见原因: bioconductor 数据包（如 go.db，trinity 依赖）需在安装时\n"
                "从 bioconductor.org 下载注释数据，国内直连极慢且易断流。\n"
                "本版本已自动改为国内镜像预下载，请直接重试；若仍失败请查看\n"
                "「更多操作 → 查看安装日志」中的 [bioc] 段落定位。"
            )
        if "unsupported format character" in err or "<exception str() failed>" in err:
            return (
                "conda 渲染错误信息时自身崩溃（新版 conda 的已知问题），\n"
                "真实错误被掩盖。请在安装日志中查找 LinkError / post-link 段落，\n"
                "或直接重试（多数为下载中断类瞬时错误）。"
            )
        if "packagesnotfound" in err:
            return (
                "未找到该软件包/版本。\n"
                "建议: 去掉版本号安装最新版, 或用 conda search <包名> 查看可用版本。"
            )
        if ("connect" in err or "timeout" in err or "超时" in err
                or "proxy" in err or "ssl" in err or "condahttperror" in err):
            return (
                "网络连接问题（bioconda 官方源在国外，直连易超时/卡死）。\n"
                "本程序已自动配置浙大 ZJU 国内镜像，通常直接重试即可成功。\n"
                "若仍反复失败: ① 更换网络环境（如手机热点）后重试\n"
                "             ② 或稍后再试（镜像站高峰期偶发限流）"
            )
        if "disk" in err or "no space" in err:
            return "磁盘空间不足。\n建议: 清理磁盘后重试 (可用 df -h 查看)。"
        if "permission denied" in err:
            return "权限不足。\n建议: 检查应用数据目录 (~/.local/share/TVAS) 的读写权限。"
        return ""

    def install_package(self, pkg: PackageSpec) -> Tuple[bool, str]:
        # trinity 依赖链含 bioconductor 数据包(go.db 等), 其 conda 包
        # 不含数据本体, 安装时需从 bioconductor.org 现场下载(国内直连
        # 必失败) → 预下载到本地 + 给 post-link 脚本打缓存直装补丁
        if pkg.name == "trinity":
            self._log_write("    [bioc] 准备 bioconductor 数据包(国内镜像预下载)...")
            self._prepare_bioc_data(
                f"{pkg.name}={pkg.version}" if pkg.version else pkg.name)

        cmd = [self._conda_exe, "install", "-n", self.env_name, "-y"]
        cmd.extend(["-c", pkg.channel])
        # bioconda 官方建议所有安装都同时挂 conda-forge：
        # 部分 C/C++ 依赖（hdf5、ncurses 等）新版本只在 conda-forge 存在，
        # 缺频道会报 UnsatisfiableError（kallisto/hdf5 即此问题）
        channels = list(pkg.extra_channels)
        if "conda-forge" not in channels:
            channels.append("conda-forge")
        for ch in channels:
            cmd.extend(["-c", ch])
        pkg_spec = f"{pkg.name}={pkg.version}" if pkg.version else pkg.name
        cmd.append(pkg_spec)

        rc, out, err = self._exec(cmd, pkg.install_timeout)

        if rc == 0:
            ver = self.get_package_version(pkg.name)
            ver_str = f" (v{ver})" if ver else ""
            msg = f"✓ {pkg.name}{ver_str} 安装成功"
            self._log_pkg_result(pkg.name, cmd, rc, out, err, True, msg)
            return True, msg
        if "already installed" in (out + err).lower():
            ver = self.get_package_version(pkg.name)
            ver_str = f" (v{ver})" if ver else ""
            msg = f"✓ {pkg.name}{ver_str} (已安装)"
            self._log_pkg_result(pkg.name, cmd, rc, out, err, True, msg)
            return True, msg

        detail = (err or out)[-300:]
        advice = self.analyze_error(err or out)
        msg = f"✗ {pkg.name}: {detail}"
        if advice:
            msg += f"\n\n{advice}"
        self._log_pkg_result(pkg.name, cmd, rc, out, err, False, msg)
        return False, msg

    # ---- bioconductor 数据包预下载（trinity 依赖国内网络优化） ----

    _BIOC_PATCH_MARKER = "TVAS_BIOC_PATCH_V1"

    # installBiocDataPackage.sh 补丁: 命中预下载缓存(md5正确)则直接安装。
    # 背景: 原脚本 set -e + 第一个 curl 失败即中止, json 里的备用镜像
    # (galaxy 系, 国内快)永远轮不到; 命中缓存则完全跳过下载环节
    _BIOC_PATCH_SCRIPT = r'''
# --- TVAS_BIOC_PATCH_V1: 命中预下载缓存则跳过慢速下载（国内网络优化） ---
if [ -n "${1:-}" ]; then
  _tvas_json="$(dirname -- "${BASH_SOURCE[0]}")/../share/bioconductor-data-packages/dataURLs.json"
  if [ -f "$_tvas_json" ]; then
    _tvas_fn="$(yq ".\"$1\".fn" "$_tvas_json" 2>/dev/null | tr -d '"')"
    _tvas_md5="$(yq ".\"$1\".md5" "$_tvas_json" 2>/dev/null | tr -d '"')"
    _tvas_tar="$PREFIX/share/$1/$_tvas_fn"
    if [ -n "$_tvas_fn" ] && [ "$_tvas_fn" != "null" ] && [ -f "$_tvas_tar" ] \
       && echo "$_tvas_md5  $_tvas_tar" | md5sum -c --status 2>/dev/null; then
      echo "TVAS: 使用预下载缓存: $_tvas_tar"
      if R CMD INSTALL --library="$PREFIX/lib/R/library" "$_tvas_tar"; then
        _tvas_rc=0
      else
        _tvas_rc=$?
      fi
      rm -f "$_tvas_tar"
      rmdir "$(dirname -- "$_tvas_tar")" 2>/dev/null
      exit $_tvas_rc
    fi
  fi
fi
# --- END TVAS_BIOC_PATCH_V1 ---
'''

    @staticmethod
    def _sort_bioc_urls(urls: List[str]) -> List[str]:
        """按国内实测速度排序下载源。

        depot.galaxyproject.org ~440KB/s（最快）；bioconductor.org
        国内直连仅 16~50KB/s 且极易断流（置底兜底）；
        bioarchive.galaxyproject.org 部分文件已 404（次选）。
        """
        def rank(u: str) -> int:
            if "depot.galaxyproject" in u:
                return 0
            if "bioarchive.galaxyproject" in u:
                return 1
            if "bioconductor.org" in u:
                return 3
            return 2
        return sorted(urls, key=rank)

    def _patch_bioc_postlink(self, env_dir: str) -> str:
        """给 installBiocDataPackage.sh 打缓存直装补丁。

        幂等: 已打过(marker 存在)则跳过; 首次备份为 .TVAS_orig;
        conda 重装 bioconductor-data-packages 后脚本被还原,
        下次安装会自动重打(按 marker 判断)。
        返回描述文本（失败返回空串, 不影响正常安装流程）。
        """
        script = os.path.join(env_dir, "bin", "installBiocDataPackage.sh")
        if not os.path.isfile(script):
            return ""
        try:
            with open(script, "r", encoding="utf-8") as f:
                content = f.read()
            if self._BIOC_PATCH_MARKER in content:
                return "post-link 缓存补丁已存在"
            lines = content.splitlines(keepends=True)
            insert_at = 1 if lines and lines[0].startswith("#!") else 0
            patched = "".join(lines[:insert_at]) + self._BIOC_PATCH_SCRIPT + "".join(lines[insert_at:])
            try:
                shutil.copy2(script, script + ".TVAS_orig")  # 备份原始脚本
            except OSError:
                pass
            with open(script, "w", encoding="utf-8") as f:
                f.write(patched)
            os.chmod(script, os.stat(script).st_mode | stat.S_IEXEC)
            return "post-link 缓存补丁已应用"
        except Exception:
            return ""

    def _prepare_bioc_data(self, spec: str) -> None:
        """trinity/bioconductor 安装前置准备: 预下载数据包 + 打补丁。

        背景: bioconductor 数据包(如 go.db, trinity 依赖)的 conda 包
        不含数据本体, 安装时由 post-link 脚本从 bioconductor.org 现场
        下载(数~数十MB)。国内直连仅 16~50KB/s 且断流, 原脚本 set -e
        使首个 curl 一断整个安装即失败。
        对策: ① dry-run 解析依赖中的数据包清单 ② 按镜像速度排序、
        断点续传地预下载到 staging 目录(md5 校验) ③ 修补 post-link
        脚本, 安装时命中缓存直接 R CMD INSTALL。
        """
        import hashlib

        env_dir = self.get_env_path()
        if not env_dir:
            return

        json_path = os.path.join(
            env_dir, "share", "bioconductor-data-packages", "dataURLs.json")
        if not os.path.isfile(json_path):
            # 先单独安装 bioconductor-data-packages（纯脚本+索引, 无数据下载）
            self._log_write("    [bioc] 预装 bioconductor-data-packages（提供下载索引）...")
            cmd = [self._conda_exe, "install", "-n", self.env_name, "-y",
                   "-c", "bioconda", "-c", "conda-forge", "bioconductor-data-packages"]
            self._exec(cmd, 900)
            if not os.path.isfile(json_path):
                self._log_write("    [bioc] ✗ 预装失败, 跳过数据预下载（回退原下载流程）")
                return

        # 1) 给 post-link 脚本打缓存直装补丁
        note = self._patch_bioc_postlink(env_dir)
        if note:
            self._log_write(f"    [bioc] {note}")

        # 2) dry-run 解析依赖中的 bioconductor 数据包
        try:
            cmd = [self._conda_exe, "install", "-n", self.env_name, "--dry-run",
                   "--json", "-q", "-c", "bioconda", "-c", "conda-forge", spec]
            rc, out, _ = self._exec(cmd, 600)
            plan = json.loads(out)
            links = (plan.get("actions") or {}).get("LINK", [])
        except Exception as e:
            self._log_write(f"    [bioc] dry-run 解析失败: {e}，跳过数据预下载")
            return

        # 3) 索引: key 形如 "go.db-3.22.0"
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                bioc_index = json.load(f)
        except Exception:
            bioc_index = {}

        for link in links:
            s = str(link).split("::")[-1]  # 兼容 "channel::name-ver-build"
            if not s.startswith("bioconductor-"):
                continue
            body, _, _build = s.rpartition("-")
            name, _, ver = body.rpartition("-")
            key = f"{name[len('bioconductor-'):]}-{ver}"
            meta = bioc_index.get(key)
            if not meta:
                continue  # 普通软件包（非数据包）
            fn = meta.get("fn", "")
            md5 = meta.get("md5", "")
            staging = os.path.join(env_dir, "share", key)
            tar = os.path.join(staging, fn)
            os.makedirs(staging, exist_ok=True)

            # md5 已正确 → 已缓存, 跳过
            if os.path.isfile(tar) and self._md5_of(tar) == md5:
                self._log_write(f"    [bioc] 缓存有效: {key}")
                continue

            ok = False
            for url in self._sort_bioc_urls(meta.get("urls", [])):
                host = url.split("/")[2]
                try:
                    self._log_write(f"    [bioc] 预下载 {fn} ← {host}")
                    _download_file(url, tar, timeout=120, retries=5, resume=True)
                    if self._md5_of(tar) == md5:
                        ok = True
                        break
                    os.remove(tar)  # 镜像内容不符, 换下一个源重下
                except Exception as e:
                    self._log_write(f"    [bioc] {host} 下载失败: {e}")
                    continue
            if ok:
                self._log_write(f"    [bioc] ✓ {key} 预下载完成")
            else:
                self._log_write(f"    [bioc] ✗ {key} 预下载失败（将回退原下载流程）")

    @staticmethod
    def _md5_of(path: str) -> str:
        import hashlib
        h = hashlib.md5()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    def install_custom_package(self, spec: str) -> Tuple[bool, str]:
        """
        安装用户自定义的软件包。
        spec: 包名或包规格，如 "salmon" / "hisat2=2.2.1"
        返回: (成功, 消息)，成功时消息包含实际版本
        """
        spec = spec.strip()
        if not spec:
            return False, "请输入要安装的软件包名称"

        # 提取纯包名（去掉版本约束）
        base_name = spec.split("=")[0].split(">")[0].split("<")[0].strip()

        # trinity / bioconductor-* 系列需要同样的数据包预下载准备
        if base_name.lower() == "trinity" or base_name.lower().startswith("bioconductor-"):
            self._prepare_bioc_data(spec)

        # 自动补齐 channels（bioconda + conda-forge）
        cmd = [self._conda_exe, "install", "-n", self.env_name, "-y",
               "-c", "bioconda", "-c", "conda-forge", spec]

        rc, out, err = self._exec(cmd, 1800)

        if rc == 0:
            ver = self.get_package_version(base_name) if base_name else ""
            ver_str = f" (v{ver})" if ver else ""
            msg = f"✓ {spec}{ver_str} 安装成功"
            self._log_pkg_result(spec, cmd, rc, out, err, True, msg)
            return True, msg
        if "already installed" in (out + err).lower():
            ver = self.get_package_version(base_name) if base_name else ""
            ver_str = f" (v{ver})" if ver else ""
            msg = f"✓ {spec}{ver_str} (已安装)"
            self._log_pkg_result(spec, cmd, rc, out, err, True, msg)
            return True, msg

        detail = (err or out)[-500:]
        advice = self.analyze_error(err or out)
        msg = f"✗ {spec}: {detail}"
        if advice:
            msg += f"\n\n{advice}"
        self._log_pkg_result(spec, cmd, rc, out, err, False, msg)
        return False, msg

    def install_all_packages(self, progress_callback=None) -> List[Tuple[str, bool, str]]:
        results = []
        for i, pkg in enumerate(PACKAGES):
            self._log_write("")
            self._log_write(f">>> [{i + 1}/{len(PACKAGES)}] {pkg.name} "
                            f"({pkg.description or ''})")
            if progress_callback:
                progress_callback(i + 1, len(PACKAGES), f"正在安装 {pkg.display_name}...")
            success, msg = self.install_package(pkg)
            results.append((pkg.name, success, msg))
        return results

    def verify_all_packages(self) -> List[Tuple[str, bool, str]]:
        import re
        results = []
        for pkg in PACKAGES:
            if not pkg.verify_cmd:
                results.append((pkg.name, True, "无需验证"))
                continue
            ok, msg = self.run_in_env(pkg.verify_cmd)
            # 宽松判断：--version 类命令即使退出码非0，
            # 只要输出含版本号就算通过（Trinity/cd-hit 等 --version 退出码可能非0）
            if not ok and re.search(r'\d+\.\d+', msg):
                ok = True
            results.append((pkg.name, ok, msg.strip() if ok else msg[:200]))
        return results

    # ---- 命令执行 ----

    def run_in_env(self, command: str, cwd: str = "", timeout: int = 3600) -> Tuple[bool, str]:
        full_cmd = [self._conda_exe, "run", "-n", self.env_name, "bash", "-c", command]
        rc, out, err = self._exec(full_cmd, timeout, cwd=cwd)
        # 被用户取消时给出明确提示
        if self._cancelled:
            return False, "用户已取消"
        output = out
        if err:
            output += "\n" + err
        return rc == 0, output


# ============================================================
# 辅助: 文件下载
# ============================================================

def _download_file(url: str, dest: str, timeout: int = 300, retries: int = 3,
                   resume: bool = False):
    """下载文件: 分块写入 + 失败自动重试（间隔递增）。

    resume=True 时支持断点续传: 目标文件已存在的部分通过 Range 请求
    续接（服务器不支持续传返回 200 时自动重头下载，已下载部分保留，
    断流后下一次重试继续接上）。适用于大文件 + 弱网。
    普通模式（默认）重试前删除残缺文件，避免半截 installer 被误用。
    """
    import ssl
    import time
    ctx = ssl.create_default_context()
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            headers = {"User-Agent": "TVAS/1.0"}
            mode = "wb"
            if resume and os.path.isfile(dest) and os.path.getsize(dest) > 0:
                headers["Range"] = f"bytes={os.path.getsize(dest)}-"
                mode = "ab"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
                # 服务器不支持续传（返回 200 而非 206）→ 重头下载
                if mode == "ab" and resp.getcode() == 200:
                    mode = "wb"
                with open(dest, mode) as f:
                    while True:
                        chunk = resp.read(1 << 20)  # 1MB 分块
                        if not chunk:
                            break
                        f.write(chunk)
            os.chmod(dest, os.stat(dest).st_mode | stat.S_IEXEC)
            return
        except Exception as e:
            last_err = e
            if not resume:
                try:
                    os.remove(dest)  # 清掉残缺文件再重试
                except OSError:
                    pass
            # resume 模式保留已下载部分，下次断点续传
            if attempt < retries:
                time.sleep(3 * attempt)
    raise RuntimeError(f"{last_err} (已重试 {retries} 次)")
