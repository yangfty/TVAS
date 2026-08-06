"""
转录组 de novo 组装软件包
"""

import os
import sys


def _read_version() -> str:
    """从 VERSION 文件读取版本号（兼容 PyInstaller 打包）"""
    try:
        base = getattr(sys, "_MEIPASS", "")
    except Exception:
        base = ""
    if not base:
        base = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    version_file = os.path.join(base, "VERSION")
    try:
        with open(version_file, "r", encoding="utf-8") as f:
            return f.read().strip() or "0.0.10"
    except Exception:
        return "0.0.10"


__version__ = _read_version()
