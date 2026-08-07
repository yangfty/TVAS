"""
转录组de novo组装软件 - 配置管理模块
"""

import os
import json
from typing import Optional

# ============================================================
# 默认配置
# ============================================================

DEFAULT_CONFIG = {
    # Conda 配置
    "conda_env_name": "rna2unigene_condaenv",
    "conda_path": "",  # 留空自动检测

    # 物种前缀 (用于序列重命名)
    "species_prefix": "Hvi",
    "gene_prefix": "Uni",  # unigene前缀

    # 分析参数默认值
    "fastp_params": {
        "quality_threshold": 20,    # -q 质量阈值
        "min_length": 50,           # -l 最小长度
        "detect_adapter": True,     # --detect_adapter_for_pe
    },

    "cd_hit_params": {
        "identity_threshold": 0.80,  # -c 相似性阈值
        "word_size": 5,              # -n 字长 (0.80~0.85 → 5)
        "accurate_mode": True,       # -g 1 精确模式
        "local_mode": True,          # -G 1 局部比对
    },

    "trinity_params": {
        "max_memory": "50G",        # --max_memory
    },

    # 默认线程数
    "default_threads": 4,

    # 当前项目工作目录
    "work_dir": "",
}


# ============================================================
# 配置管理器
# ============================================================

class ConfigManager:
    """管理软件配置：加载、保存、读写配置项"""

    def __init__(self, config_file: Optional[str] = None):
        self._config = dict(DEFAULT_CONFIG)
        self._config_file = config_file

        if config_file and os.path.exists(config_file):
            self.load(config_file)

    # ---- 文件读写 ----

    def load(self, path: str) -> None:
        try:
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            self._config.update(loaded)
            self._config_file = path
        except Exception as e:
            print(f"[警告] 加载配置文件失败: {e}，使用默认配置")

    def save(self, path: Optional[str] = None) -> None:
        target = path or self._config_file
        if not target:
            return
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            json.dump(self._config, f, indent=2, ensure_ascii=False)

    # ---- 通用访问 ----

    def get(self, key: str, default=None):
        return self._config.get(key, default)

    def set(self, key: str, value) -> None:
        self._config[key] = value

    # ---- 便捷方法 ----

    @property
    def conda_env_name(self) -> str:
        return self._config["conda_env_name"]

    @property
    def conda_path(self) -> str:
        return self._config.get("conda_path", "")

    @property
    def species_prefix(self) -> str:
        return self._config["species_prefix"]

    @property
    def gene_prefix(self) -> str:
        return self._config["gene_prefix"]

    @property
    def default_threads(self) -> int:
        return self._config["default_threads"]

    @property
    def work_dir(self) -> str:
        return self._config.get("work_dir", "")

    @work_dir.setter
    def work_dir(self, value: str):
        self._config["work_dir"] = value

    def fastp_params(self) -> dict:
        return self._config["fastp_params"]

    def cd_hit_params(self) -> dict:
        return self._config["cd_hit_params"]

    def trinity_params(self) -> dict:
        return self._config["trinity_params"]
