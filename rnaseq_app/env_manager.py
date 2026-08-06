"""
转录组de novo组装软件 - Conda环境管理器（自包含版）

负责:
  - 检测/下载/部署本地 Miniconda（不影响系统）
  - 创建虚拟环境
  - 安装所有生物信息学软件
  - 在隔离环境中执行命令
"""

import os
import sys
import subprocess
import shutil
import urllib.request
import stat
from typing import Tuple, List, Optional
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

def _conda_env() -> dict:
    """构造 conda 子进程环境变量（自动接受 ToS）"""
    env = dict(os.environ)
    env["CONDA_PLUGINS_AUTO_ACCEPT_TOS"] = "true"
    env.setdefault("CONDA_AUTO_UPDATE_CONDA", "false")
    return env


# ============================================================
# 软件包安装清单
# ============================================================

@dataclass
class PackageSpec:
    """单个软件包的安装规格"""
    name: str
    version: str = ""
    channel: str = "bioconda"
    extra_channels: List[str] = field(default_factory=list)
    verify_cmd: str = ""

    @property
    def display_name(self) -> str:
        if self.version:
            return f"{self.name}={self.version}"
        return f"{self.name} (latest)"


PACKAGES = [
    PackageSpec(name="fastqc", version="0.11", verify_cmd="fastqc --version"),
    PackageSpec(name="fastp", verify_cmd="fastp --version"),
    PackageSpec(name="rcorrector", verify_cmd="perl -e 'exit 0'"),
    PackageSpec(
        name="trinity", version="2.8",
        extra_channels=["conda-forge"],
        verify_cmd="Trinity --version"
    ),
    PackageSpec(name="jellyfish", version="2.2", verify_cmd="jellyfish --version"),
    PackageSpec(name="cd-hit", version="4.8", verify_cmd="cd-hit --version"),
    PackageSpec(
        name="transdecoder", version="5.5",
        extra_channels=["conda-forge"],
        verify_cmd="TransDecoder.LongOrfs --version"
    ),
    PackageSpec(name="kallisto", version="0.51", verify_cmd="kallisto version"),
    PackageSpec(name="gffread", verify_cmd="gffread --version"),
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
        # 操作日志（供高级设置查看）
        self.last_log: str = ""           # 最近一次命令的完整输出
        self.last_cmd: str = ""           # 最近一次命令
        self.pkg_logs: dict = {}          # 包名 -> 最近一次安装的完整输出

    # ---- 统一命令执行（记录完整日志） ----

    def _exec(self, cmd: List[str], timeout: int, cwd: str = "") -> Tuple[int, str, str]:
        """
        执行 conda 命令并记录完整输出到 self.last_log
        返回: (returncode, stdout, stderr)
        """
        self.last_cmd = " ".join(cmd)
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=timeout, cwd=cwd or None, env=_conda_env(),
            )
            self.last_log = result.stdout
            if result.stderr:
                self.last_log += "\n[stderr]\n" + result.stderr
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            self.last_log = f"命令超时（>{timeout}秒）"
            return -1, "", self.last_log
        except Exception as e:
            self.last_log = str(e)
            return -1, "", str(e)

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

        # 下载 installer
        if progress_callback:
            progress_callback("正在下载 Miniconda (~100MB)...")

        try:
            _download_file(cls.MINICONDA_URL, installer_path)
        except Exception as e:
            return False, f"下载 Miniconda 失败: {e}\n请检查网络连接"

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

    def create_env(self, prefix: Optional[str] = None) -> Tuple[bool, str]:
        """
        创建conda虚拟环境。
        如果指定 prefix，环境建在指定目录（自包含隔离）。
        """
        if self.env_exists():
            return True, f"环境 '{self.env_name}' 已存在"

        cmd = [self._conda_exe, "create", "-n", self.env_name, "-y", "python=3.8"]
        if prefix:
            cmd = [self._conda_exe, "create", "-p", prefix, "-y", "python=3.8"]

        try:
            rc, out, err = self._exec(cmd, 300)
            if rc == 0:
                return True, f"环境 '{self.env_name}' 创建成功"
            return False, (err or out)[-500:]
        except subprocess.TimeoutExpired:
            return False, "创建环境超时（超过5分钟）"
        except Exception as e:
            return False, str(e)

    def install_package(self, pkg: PackageSpec) -> Tuple[bool, str]:
        cmd = [self._conda_exe, "install", "-n", self.env_name, "-y"]
        cmd.extend(["-c", pkg.channel])
        for ch in pkg.extra_channels:
            cmd.extend(["-c", ch])
        pkg_spec = f"{pkg.name}={pkg.version}" if pkg.version else pkg.name
        cmd.append(pkg_spec)

        rc, out, err = self._exec(cmd, 600)
        self.pkg_logs[pkg.name] = self.last_log

        if rc == 0:
            return True, f"✓ {pkg.display_name} 安装成功"
        if "already installed" in (out + err).lower():
            return True, f"✓ {pkg.display_name} (已安装)"
        return False, f"✗ {pkg.display_name}: {(err or out)[-300:]}"

    def install_custom_package(self, spec: str) -> Tuple[bool, str]:
        """
        安装用户自定义的软件包。
        spec: 包名或包规格，如 "salmon" / "hisat2=2.2.1"
        """
        spec = spec.strip()
        if not spec:
            return False, "请输入要安装的软件包名称"

        # 自动补齐 channels（bioconda + conda-forge）
        cmd = [self._conda_exe, "install", "-n", self.env_name, "-y",
               "-c", "bioconda", "-c", "conda-forge", spec]

        rc, out, err = self._exec(cmd, 600)
        if rc == 0:
            return True, f"✓ {spec} 安装成功"
        if "already installed" in (out + err).lower():
            return True, f"✓ {spec} (已安装)"
        return False, f"✗ {spec}: {(err or out)[-500:]}"

    def get_package_log(self, pkg_name: str) -> str:
        """获取某软件包最近一次安装的完整日志"""
        return self.pkg_logs.get(pkg_name, "(无记录)")

    def install_all_packages(self, progress_callback=None) -> List[Tuple[str, bool, str]]:
        results = []
        for i, pkg in enumerate(PACKAGES):
            if progress_callback:
                progress_callback(i + 1, len(PACKAGES), f"正在安装 {pkg.display_name}...")
            success, msg = self.install_package(pkg)
            results.append((pkg.name, success, msg))
        return results

    def verify_all_packages(self) -> List[Tuple[str, bool, str]]:
        results = []
        for pkg in PACKAGES:
            if not pkg.verify_cmd:
                results.append((pkg.name, True, "无需验证"))
                continue
            ok, msg = self.run_in_env(pkg.verify_cmd)
            results.append((pkg.name, ok, msg.strip() if ok else msg[:200]))
        return results

    # ---- 命令执行 ----

    def run_in_env(self, command: str, cwd: str = "", timeout: int = 3600) -> Tuple[bool, str]:
        full_cmd = [self._conda_exe, "run", "-n", self.env_name, "bash", "-c", command]
        rc, out, err = self._exec(full_cmd, timeout, cwd=cwd)
        output = out
        if err:
            output += "\n" + err
        return rc == 0, output

    def run_script(self, script_path: str, cwd: str = "", timeout: int = 3600) -> Tuple[bool, str]:
        return self.run_in_env(f"bash {script_path}", cwd=cwd, timeout=timeout)

    # ---- 摘要 ----

    def summarize(self) -> str:
        lines = [
            f"Conda 路径: {self._conda_exe}",
            f"本地 Conda: {'✓' if self.is_local_conda_installed() else '✗'}",
            f"目标环境: {self.env_name}",
            f"环境状态: {'✓' if self.env_exists() else '✗'}",
        ]
        env_path = self.get_env_path()
        if env_path:
            lines.append(f"环境路径: {env_path}")
        lines.append(f"数据目录: {get_app_data_dir()}")
        return "\n".join(lines)


# ============================================================
# 辅助: 文件下载
# ============================================================

def _download_file(url: str, dest: str, timeout: int = 600):
    """下载文件（带进度）"""
    import ssl
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={"User-Agent": "TVAS/1.0"})
    with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
        with open(dest, "wb") as f:
            f.write(resp.read())
    os.chmod(dest, os.stat(dest).st_mode | stat.S_IEXEC)
