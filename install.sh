#!/bin/bash
# ============================================================
# 转录组 De Novo 组装分析软件 - 一键安装脚本
# ============================================================
#
# 将打包好的程序安装到系统，并创建桌面快捷方式
#
# 使用: chmod +x install.sh && ./install.sh
#
# 安装内容:
#   1. 可执行文件 → ~/.local/bin/rnaseq-denovo
#   2. 应用图标   → ~/.local/share/icons/hicolor/128x128/apps/rnaseq-denovo.png
#   3. 桌面快捷   → ~/.local/share/applications/rnaseq-denovo.desktop
#   4. 也可选安装到系统级 (/usr/local/bin 需要 sudo)
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 配置
APP_NAME="rnaseq-denovo"
APP_DISPLAY_NAME="转录组DeNovo组装"
ICON_SIZE="128"

echo "============================================"
echo "  $APP_DISPLAY_NAME - 安装向导"
echo "============================================"
echo ""

# ---- 选择安装模式 ----
echo "请选择安装模式:"
echo "  1) 用户安装 (推荐, 无需sudo)"
echo "     → ~/.local/bin/           (可执行文件)"
echo "     → ~/.local/share/          (桌面快捷方式和图标)"
echo ""
echo "  2) 系统安装 (需要sudo权限)"
echo "     → /usr/local/bin/          (可执行文件)"
echo "     → /usr/share/              (桌面快捷方式和图标)"
echo ""
read -p "请选择 [1-2, 默认1]: " mode
mode=${mode:-1}

if [ "$mode" = "2" ]; then
    PREFIX="/usr/local"
    BIN_DIR="$PREFIX/bin"
    APPS_DIR="/usr/share/applications"
    ICONS_DIR="/usr/share/icons/hicolor/${ICON_SIZE}x${ICON_SIZE}/apps"
    NEED_SUDO=1
else
    PREFIX="$HOME/.local"
    BIN_DIR="$PREFIX/bin"
    APPS_DIR="$HOME/.local/share/applications"
    ICONS_DIR="$HOME/.local/share/icons/hicolor/${ICON_SIZE}x${ICON_SIZE}/apps"
    NEED_SUDO=0
fi

# ---- 查找可执行文件 ----
EXECUTABLE="dist/转录组DeNovo组装"
if [ ! -f "$EXECUTABLE" ]; then
    echo ""
    echo "[错误] 未找到打包好的可执行文件: $EXECUTABLE"
    echo ""
    echo "请先运行 build.sh 进行打包:"
    echo "  ./build.sh"
    echo ""
    echo "或者以开发模式运行:"
    echo "  ./run.sh"
    exit 1
fi

SUDO=""
if [ "$NEED_SUDO" = "1" ]; then
    SUDO="sudo"
    echo ""
    echo "[提示] 系统安装需要管理员权限"
fi

echo ""
echo "安装信息:"
echo "  可执行文件:  $BIN_DIR/$APP_NAME"
echo "  桌面快捷方式: $APPS_DIR/$APP_NAME.desktop"
echo "  应用图标:    $ICONS_DIR/$APP_NAME.png"
echo ""

read -p "确认安装? [Y/n]: " confirm
confirm=${confirm:-Y}
if [ "$confirm" != "Y" ] && [ "$confirm" != "y" ]; then
    echo "已取消"
    exit 0
fi

# ---- 1. 安装可执行文件 ----
echo ""
echo "[1/4] 安装可执行文件..."
$SUDO mkdir -p "$BIN_DIR"
$SUDO cp "$EXECUTABLE" "$BIN_DIR/$APP_NAME"
$SUDO chmod +x "$BIN_DIR/$APP_NAME"
echo "  ✓ 已安装到 $BIN_DIR/$APP_NAME"

# ---- 2. 安装图标 ----
echo "[2/4] 安装应用图标..."
ICON_SRC="rnaseq_app/resources/icon.png"

# 如果没有PNG图标，尝试从SVG生成
if [ ! -f "$ICON_SRC" ] || [ ! -s "$ICON_SRC" ]; then
    echo "  正在从SVG生成PNG图标..."
    if command -v rsvg-convert &>/dev/null; then
        rsvg-convert -w "$ICON_SIZE" -h "$ICON_SIZE" "rnaseq_app/resources/icon.svg" -o "$ICON_SRC"
    elif command -v convert &>/dev/null; then
        convert -background none -resize ${ICON_SIZE}x${ICON_SIZE} "rnaseq_app/resources/icon.svg" "$ICON_SRC"
    else
        echo "  [警告] 无法生成PNG图标，跳过"
    fi
fi

if [ -f "$ICON_SRC" ] && [ -s "$ICON_SRC" ]; then
    $SUDO mkdir -p "$ICONS_DIR"
    $SUDO cp "$ICON_SRC" "$ICONS_DIR/$APP_NAME.png"
    echo "  ✓ 图标已安装"
else
    echo "  [跳过] 无可用图标"
fi

# ---- 3. 安装桌面快捷方式 ----
echo "[3/4] 安装桌面快捷方式..."
$SUDO mkdir -p "$APPS_DIR"

# 创建 .desktop 文件
DESKTOP_FILE="$APPS_DIR/$APP_NAME.desktop"
$SUDO bash -c "cat > $DESKTOP_FILE" << DESKTOPEOF
[Desktop Entry]
Name=$APP_DISPLAY_NAME
Name[zh_CN]=$APP_DISPLAY_NAME
Comment=转录组测序数据 De Novo 组装分析工具
Comment[zh_CN]=转录组测序数据 De Novo 组装分析工具
Exec=$BIN_DIR/$APP_NAME
Icon=$APP_NAME
Terminal=false
Type=Application
Categories=Science;Biology;Education;
StartupNotify=true
Encoding=UTF-8
DESKTOPEOF

$SUDO chmod +x "$DESKTOP_FILE"
echo "  ✓ 桌面快捷方式已创建"

# ---- 4. 更新图标缓存 ----
echo "[4/4] 更新图标缓存..."
if command -v update-icon-caches &>/dev/null 2>&1; then
    $SUDO update-icon-caches "$ICONS_DIR/../.." 2>/dev/null || true
    echo "  ✓ 图标缓存已更新"
elif command -v gtk-update-icon-cache &>/dev/null 2>&1; then
    $SUDO gtk-update-icon-cache "${ICONS_DIR%/*/*}/hicolor" 2>/dev/null || true
    echo "  ✓ 图标缓存已更新"
else
    echo "  [跳过] 无需更新图标缓存"
fi

# ---- 完成 ----
echo ""
echo "============================================"
echo "  安装完成!"
echo "============================================"
echo ""
echo "  现在你可以通过以下方式启动:"
echo "  1. 在应用程序菜单中搜索「转录组DeNovo组装」"
echo "  2. 在终端中运行: $APP_NAME"
echo "  3. 双击桌面快捷方式（如已显示）"
echo ""
echo "  命令行用法:"
echo "    $APP_NAME                     # 启动GUI"
echo "    $APP_NAME --help              # 查看帮助"
echo ""

# 检查 PATH 是否包含 BIN_DIR
if [ "$mode" = "1" ]; then
    if ! echo "$PATH" | grep -q "$BIN_DIR"; then
        echo "  [提示] $BIN_DIR 不在你的 PATH 中"
        echo "  请将以下行添加到 ~/.bashrc:"
        echo "    export PATH=\"\$HOME/.local/bin:\$PATH\""
        echo ""
    fi
fi
