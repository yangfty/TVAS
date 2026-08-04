#!/bin/bash
# ============================================================
# 转录组 De Novo 组装分析软件 - UOS/Linux 启动脚本
# ============================================================
#
# 使用方法:
#   chmod +x run.sh
#   ./run.sh
#
# 首次运行会自动检测并提示安装依赖
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "============================================"
echo "  转录组 De Novo 组装分析软件 v1.0"
echo "  适用平台: UOS / Debian / Ubuntu / CentOS"
echo "============================================"
echo ""

# ---- 检查 Python3 ----
if ! command -v python3 &>/dev/null; then
    echo "[错误] 未找到 python3，请先安装 Python 3.6+"
    echo "  UOS/Debian/Ubuntu: sudo apt install python3 python3-pip"
    echo "  CentOS/RHEL:        sudo yum install python3 python3-pip"
    exit 1
fi

PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
echo "[检测] Python 版本: $PYTHON_VERSION"

# ---- 检查 Conda ----
if command -v conda &>/dev/null; then
    CONDA_VER=$(conda --version 2>&1)
    echo "[检测] Conda 已安装: $CONDA_VER"
else
    echo "[提示] 未检测到 Conda，请先安装 Miniconda"
    echo ""
    echo "安装方法 (Miniconda):"
    echo "  wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh"
    echo "  bash Miniconda3-latest-Linux-x86_64.sh"
    echo "  # 安装完成后重启终端或运行: source ~/.bashrc"
    echo ""
    echo "是否继续启动软件? (y/n)"
    read -r answer
    if [ "$answer" != "y" ] && [ "$answer" != "Y" ]; then
        exit 0
    fi
fi

# ---- 检查 PyQt5 ----
python3 -c "import PyQt5" 2>/dev/null && PYQT_OK=1 || PYQT_OK=0

if [ "$PYQT_OK" -eq 0 ]; then
    echo ""
    echo "[提示] 未安装 PyQt5，正在尝试安装..."
    echo ""
    echo "安装方式选择:"
    echo "  1) pip 安装 (推荐)"
    echo "  2) apt 安装 (系统包管理器)"
    echo "  3) 跳过 (自行安装后重新运行)"
    echo ""
    read -p "请选择 [1-3]: " choice

    case $choice in
        1)
            echo "正在通过 pip 安装 PyQt5..."
            python3 -m pip install PyQt5 --user
            ;;
        2)
            echo "正在通过 apt 安装 PyQt5..."
            sudo apt update && sudo apt install -y python3-pyqt5
            ;;
        3)
            echo "请手动安装 PyQt5 后重新运行: pip install PyQt5"
            exit 0
            ;;
        *)
            echo "无效选择，退出"
            exit 1
            ;;
    esac

    # 再次验证
    python3 -c "import PyQt5" 2>/dev/null || {
        echo "[错误] PyQt5 安装失败，请手动安装"
        echo "  pip install PyQt5"
        echo "  或"
        echo "  sudo apt install python3-pyqt5"
        exit 1
    }
    echo "[完成] PyQt5 安装成功"
fi

# ---- 启动软件 ----
echo ""
echo "启动中..."
echo ""

python3 main.py

echo ""
echo "软件已退出"
