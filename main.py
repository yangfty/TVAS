#!/usr/bin/env python3
"""
转录组 De Novo 组装分析软件 - 主入口

在 UOS / Debian / Ubuntu 等 Linux 系统上运行:
    python main.py

依赖安装:
    pip install PyQt5
    或
    sudo apt install python3-pyqt5
"""

import sys
import os


def main():
    # 确保能找到 rnaseq_app 包
    app_dir = os.path.dirname(os.path.abspath(__file__))
    if app_dir not in sys.path:
        sys.path.insert(0, app_dir)

    from PyQt5.QtWidgets import QApplication
    from PyQt5.QtCore import Qt

    # 高DPI适配
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setApplicationName("转录组DeNovo组装")
    app.setOrganizationName("RNAseqTools")

    # 设置应用样式
    app.setStyle("Fusion")

    # 加载配置
    from rnaseq_app.config import ConfigManager
    config_file = os.path.join(app_dir, "rnaseq_config.json")
    config = ConfigManager(config_file)

    # 创建主窗口
    from rnaseq_app.main_window import MainWindow
    window = MainWindow(config)
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
