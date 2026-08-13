"""
转录组分析软件 - 系统终端启动

调用 UOS 系统终端（deepin-terminal / gnome-terminal / xterm），
自动 cd 到工作目录并 conda activate 进入分析环境。
"""

import os
import shutil
import subprocess
from typing import Tuple

from .env_manager import CondaEnvManager, get_app_data_dir


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
