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
    # 注意: 配置必须放在用户数据目录。PyInstaller --onefile 打包后
    # app_dir 是每次运行都不同的临时解压目录（/tmp/_MEIxxx），退出即销毁，
    # 配置放那里永远存不下来——导致每次打开软件都要重新检测/创建环境
    from rnaseq_app.config import ConfigManager
    from rnaseq_app.env_manager import get_app_data_dir
    config_file = os.path.join(get_app_data_dir(), "config.json")
    config = ConfigManager(config_file)

    # 创建主窗口
    from rnaseq_app.main_window import MainWindow
    window = MainWindow(config)
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
