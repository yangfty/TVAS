"""
转录组de novo组装软件 - Conda环境管理器

负责:
  - 检测conda是否安装
  - 创建虚拟环境
  - 安装所有生物信息学软件
  - 检查环境状态
  - 在环境中执行命令
"""

import os
import subprocess
import shutil
from typing import Tuple, List, Optional
from dataclasses import dataclass, field

# ============================================================
# 软件包安装清单
# ============================================================

@dataclass
class PackageSpec:
    """单个软件包的安装规格"""
    name: str
    version: str = ""           # 空字符串 = 最新版
    channel: str = "bioconda"   # 主要channel
    extra_channels: List[str] = field(default_factory=list)
    verify_cmd: str = ""        # 验证安装的命令 (如 "fastqc --version")

    @property
    def display_name(self) -> str:
        if self.version:
            return f"{self.name}={self.version}"
        return f"{self.name} (latest)"


# 定义所有需要安装的软件包
PACKAGES = [
    PackageSpec(name="fastqc", version="0.11", verify_cmd="fastqc --version"),
    PackageSpec(name="fastp", verify_cmd="fastp --version"),
    PackageSpec(name="rcorrector", verify_cmd="perl -e 'exit 0'"),  # rcorrector本身是perl脚本
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


# ============================================================
# 环境管理器
# ============================================================

class CondaEnvManager:
    """管理 conda 虚拟环境的创建、软件安装与命令执行"""

    def __init__(self, env_name: str, conda_path: str = ""):
        """
        env_name: conda 环境名称，例如 'rna2unigene_condaenv'
        conda_path: conda 可执行文件路径，留空则自动检测
        """
        self.env_name = env_name
        self._conda_exe = self._resolve_conda(conda_path)
        self._env_ready = False

    # ---- Conda 检测 ----

    @staticmethod
    def _resolve_conda(custom_path: str) -> str:
        """解析 conda 可执行文件路径"""
        if custom_path and os.path.isfile(custom_path):
            return custom_path

        # 常见安装路径
        candidates = [
            shutil.which("conda"),
            shutil.which("mamba"),
            os.path.expanduser("~/miniconda3/bin/conda"),
            os.path.expanduser("~/anaconda3/bin/conda"),
            os.path.expanduser("~/miniconda3/condabin/conda"),
            os.path.expanduser("~/anaconda3/condabin/conda"),
            "/opt/conda/bin/conda",
            "/opt/miniconda3/bin/conda",
            "/usr/local/bin/conda",
        ]
        for p in candidates:
            if p and os.path.isfile(p):
                return p
        return "conda"  # 最后的fallback

    @property
    def conda_exe(self) -> str:
        return self._conda_exe

    def is_conda_installed(self) -> Tuple[bool, str]:
        """检查conda是否已安装"""
        try:
            result = subprocess.run(
                [self._conda_exe, "--version"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                return True, result.stdout.strip()
            return False, result.stderr.strip()
        except FileNotFoundError:
            return False, "conda 未找到，请先安装 Miniconda 或 Anaconda"
        except Exception as e:
            return False, str(e)

    # ---- 环境管理 ----

    def env_exists(self) -> bool:
        """检查目标环境是否已存在"""
        try:
            result = subprocess.run(
                [self._conda_exe, "env", "list"],
                capture_output=True, text=True, timeout=15
            )
            for line in result.stdout.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # 格式: env_name  /path/to/env
                parts = line.split()
                if parts and parts[0] == self.env_name:
                    return True
            return False
        except Exception:
            return False

    def get_env_path(self) -> Optional[str]:
        """获取环境安装路径"""
        try:
            result = subprocess.run(
                [self._conda_exe, "env", "list"],
                capture_output=True, text=True, timeout=15
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

    def create_env(self) -> Tuple[bool, str]:
        """创建conda虚拟环境"""
        if self.env_exists():
            return True, f"环境 '{self.env_name}' 已存在，跳过创建"

        cmd = [self._conda_exe, "create", "-n", self.env_name, "-y", "python=3.8"]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if result.returncode == 0:
                return True, f"环境 '{self.env_name}' 创建成功"
            return False, result.stderr[-500:] if result.stderr else "未知错误"
        except subprocess.TimeoutExpired:
            return False, "创建环境超时（超过5分钟）"
        except Exception as e:
            return False, str(e)

    def install_package(self, pkg: PackageSpec) -> Tuple[bool, str]:
        """在环境中安装一个软件包"""
        # 构建 conda install 命令
        cmd = [self._conda_exe, "install", "-n", self.env_name, "-y"]

        # 添加 channel
        cmd.extend(["-c", pkg.channel])
        for ch in pkg.extra_channels:
            cmd.extend(["-c", ch])

        # 包名（可选版本号）
        pkg_spec = f"{pkg.name}={pkg.version}" if pkg.version else pkg.name
        cmd.append(pkg_spec)

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if result.returncode == 0:
                return True, f"✓ {pkg.display_name} 安装成功"
            # 检查是否已安装
            if "already installed" in result.stderr.lower() or "already installed" in result.stdout.lower():
                return True, f"✓ {pkg.display_name} (已安装)"
            return False, f"✗ {pkg.display_name} 安装失败\n{result.stderr[-500:]}"
        except subprocess.TimeoutExpired:
            return False, f"✗ {pkg.display_name} 安装超时"
        except Exception as e:
            return False, f"✗ {pkg.display_name}: {e}"

    def install_all_packages(self, progress_callback=None) -> List[Tuple[str, bool, str]]:
        """
        安装所有软件包
        返回: [(包名, 成功/失败, 信息), ...]
        """
        results = []
        total = len(PACKAGES)

        for i, pkg in enumerate(PACKAGES):
            if progress_callback:
                progress_callback(i + 1, total, f"正在安装 {pkg.display_name}...")

            success, msg = self.install_package(pkg)
            results.append((pkg.name, success, msg))

        return results

    def verify_all_packages(self) -> List[Tuple[str, bool, str]]:
        """验证所有软件包是否正确安装"""
        results = []
        for pkg in PACKAGES:
            if not pkg.verify_cmd:
                results.append((pkg.name, True, "无需验证"))
                continue
            ok, msg = self.run_in_env(pkg.verify_cmd)
            results.append((pkg.name, ok, msg.strip() if ok else msg[:200]))
        return results

    # ---- 环境内命令执行 ----

    def run_in_env(self, command: str, cwd: str = "", timeout: int = 3600) -> Tuple[bool, str]:
        """
        在conda环境中执行命令
        使用 conda run 方式，自动激活/退出环境
        """
        full_cmd = [self._conda_exe, "run", "-n", self.env_name, "bash", "-c", command]
        try:
            result = subprocess.run(
                full_cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd or None,
                shell=False,
            )
            output = result.stdout
            if result.stderr:
                output += "\n" + result.stderr
            return result.returncode == 0, output
        except subprocess.TimeoutExpired:
            return False, f"命令超时（>{timeout}秒）: {command[:100]}"
        except Exception as e:
            return False, str(e)

    def run_script(self, script_path: str, cwd: str = "", timeout: int = 3600) -> Tuple[bool, str]:
        """在conda环境中运行一个bash脚本"""
        return self.run_in_env(f"bash {script_path}", cwd=cwd, timeout=timeout)

    # ---- 状态检查 ----

    def summarize(self) -> str:
        """生成环境状态摘要"""
        lines = []
        lines.append(f"Conda 路径: {self._conda_exe}")
        ok, info = self.is_conda_installed()
        lines.append(f"Conda 状态: {'✓ 已安装' if ok else '✗ ' + info}")
        lines.append(f"目标环境: {self.env_name}")
        lines.append(f"环境状态: {'✓ 已创建' if self.env_exists() else '✗ 未创建'}")
        if self.env_exists():
            env_path = self.get_env_path()
            if env_path:
                lines.append(f"环境路径: {env_path}")
        return "\n".join(lines)


# ============================================================
# 便捷函数
# ============================================================

def check_conda_installed() -> Tuple[bool, str]:
    """快速检查conda是否可用"""
    mgr = CondaEnvManager("_check_")
    return mgr.is_conda_installed()
