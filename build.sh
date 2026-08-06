#!/bin/bash
# ============================================================
# 转录组 De Novo 组装分析软件 - 打包构建脚本
# ============================================================
#
# 用法:
#   ./build.sh              # PyInstaller 打包 (独立可执行文件)
#   ./build.sh --deb        # 打包 + 构建 .deb 安装包 (用于分发/UOS商店)
#   ./build.sh --release    # 发布模式 (打包 + deb + 生成Release目录)
#
# 输出:
#   dist/转录组DeNovo组装              # 独立可执行文件
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# ---- 版本号 ----
if [ -f VERSION ]; then
    VERSION=$(cat VERSION | tr -d '[:space:]')
else
    VERSION="0.0.6"
fi

APP_NAME="转录组DeNovo组装"
DEB_NAME="TVAS"

echo "============================================"
echo "  $APP_NAME - 打包构建 v$VERSION"
echo "============================================"
echo ""

# ---- 解析参数 ----
BUILD_DEB=0
RELEASE_MODE=0
for arg in "$@"; do
    case $arg in
        --deb)
            BUILD_DEB=1
            ;;
        --release)
            BUILD_DEB=1
            RELEASE_MODE=1
            ;;
    esac
done

# ---- 检查 Python3 ----
if ! command -v python3 &>/dev/null; then
    echo "[错误] 未找到 python3"
    exit 1
fi

# ---- 安装 PyInstaller ----
echo "[1/5] 检查 PyInstaller..."
python3 -c "import PyInstaller" 2>/dev/null || {
    echo "  正在安装 PyInstaller..."
    python3 -m pip install pyinstaller --user
}

# ---- 安装 PyQt5 ----
echo "[2/5] 检查 PyQt5..."
python3 -c "import PyQt5" 2>/dev/null || {
    echo "  正在安装 PyQt5..."
    python3 -m pip install PyQt5 --user
}

# ---- 生成 PNG 图标 ----
echo "[3/5] 生成应用图标..."
ICON_SVG="rnaseq_app/resources/icon.svg"
ICON_PNG="rnaseq_app/resources/icon.png"

if command -v rsvg-convert &>/dev/null; then
    rsvg-convert -w 256 -h 256 "$ICON_SVG" -o "$ICON_PNG"
    echo "  [rsvg-convert] 256x256 PNG"
elif command -v convert &>/dev/null; then
    convert -background none -resize 256x256 "$ICON_SVG" "$ICON_PNG"
    echo "  [ImageMagick] 256x256 PNG"
else
    python3 -c "
from PyQt5.QtSvg import QSvgRenderer
from PyQt5.QtGui import QImage, QPainter
from PyQt5.QtCore import Qt
import sys
app = __import__('sys').modules.get('PyQt5.QtWidgets') or __import__('PyQt5.QtWidgets', fromlist=['QApplication'])
qapp = app.QApplication(sys.argv)
r = QSvgRenderer('$ICON_SVG')
img = QImage(256, 256, QImage.Format_ARGB32)
img.fill(Qt.transparent)
p = QPainter(img); r.render(p); p.end()
img.save('$ICON_PNG')
qapp.quit()
" 2>/dev/null || touch "$ICON_PNG"
    echo "  [PyQt5] 256x256 PNG"
fi

# ---- PyInstaller 打包 ----
echo "[4/5] PyInstaller 打包中..."
echo "  (这可能需要 1-2 分钟)"
echo ""

pyinstaller \
    --onefile \
    --windowed \
    --name="$APP_NAME" \
    --icon="${ICON_PNG:-$ICON_SVG}" \
    --add-data="VERSION:." \
    --add-data="rnaseq_app/resources/icon.svg:rnaseq_app/resources" \
    --add-data="rnaseq_app/resources/icon.png:rnaseq_app/resources" \
    --add-data="scripts:scripts" \
    --hidden-import="PyQt5.QtSvg" \
    --hidden-import="PyQt5.QtXml" \
    --hidden-import="pkgutil" \
    --hidden-import="importlib" \
    --hidden-import="importlib.util" \
    --collect-all="PyQt5" \
    --clean \
    --noconfirm \
    main.py

BIN_SIZE=$(du -h "dist/$APP_NAME" 2>/dev/null | cut -f1 || echo "?")
echo "  ✓ 可执行文件: dist/$APP_NAME ($BIN_SIZE)"

# ---- DEB 打包 ----
if [ "$BUILD_DEB" -eq 1 ]; then
    echo ""
    echo "[5/5] 构建 Debian 安装包..."

    if ! command -v dpkg-deb &>/dev/null && ! command -v dpkg &>/dev/null; then
        echo "  [警告] 未找到 dpkg-deb，无法构建 .deb 包"
        echo "  提示: 此步骤需要在 UOS/Debian/Ubuntu 系统上运行"
    else
        # 临时构建目录
        DEB_BUILD_DIR="deb_build/$DEB_NAME-$VERSION"
        mkdir -p "$DEB_BUILD_DIR/DEBIAN"

        # 安装路径 (UOS 规范: /opt/apps/${appid})
        APPID="org.horticulture.rnaseq-denovo"
        INSTALL_ROOT="$DEB_BUILD_DIR/opt/apps/$APPID"

        # ---- control 文件 ----
        cat > "$DEB_BUILD_DIR/DEBIAN/control" << CONTROL
Package: $DEB_NAME
Version: $VERSION
Architecture: amd64
Maintainer: RNA-seq Analysis Tools <dev@example.com>
Section: science
Priority: optional
Depends: python3, libxcb-xinerama0, libxcb-icccm4, libxcb-image0, libxcb-keysyms1, libxcb-render-util0, libxkbcommon-x11-0, libegl1
Recommends: conda
Homepage: https://github.com/yangfty/TVAS
Description: 转录组DeNovo组装分析工具 (GUI)
  RNA-seq De Novo Assembly GUI
  为没有参考基因组的物种提供一站式转录组组装解决方案。
  完整流程：FastQC → Fastp → Rcorrector → Trinity → CD-HIT → TransDecoder → Gffread
CONTROL

        # ---- 复制文件 ----
        mkdir -p "$INSTALL_ROOT/files/bin"
        mkdir -p "$INSTALL_ROOT/files/scripts"
        mkdir -p "$INSTALL_ROOT/entries/applications"
        mkdir -p "$INSTALL_ROOT/entries/icons/hicolor/128x128/apps"
        mkdir -p "$INSTALL_ROOT/entries/icons/hicolor/256x256/apps"

        cp "dist/$APP_NAME" "$INSTALL_ROOT/files/bin/rnaseq-denovo"
        cp scripts/*.py "$INSTALL_ROOT/files/scripts/"
        cp "$ICON_PNG" "$INSTALL_ROOT/entries/icons/hicolor/128x128/apps/${APPID}.png"
        cp "$ICON_PNG" "$INSTALL_ROOT/entries/icons/hicolor/256x256/apps/${APPID}.png"

        # ---- desktop 文件 ----
        cat > "$INSTALL_ROOT/entries/applications/${APPID}.desktop" << DESKTOP
[Desktop Entry]
Name=$APP_NAME
Name[zh_CN]=$APP_NAME
Comment=转录组测序数据 De Novo 组装分析工具
Comment[zh_CN]=为没有参考基因组的物种提供一站式转录组组装方案
Exec=/opt/apps/$APPID/files/bin/rnaseq-denovo
Icon=$APPID
Terminal=false
Type=Application
Categories=Science;Biology;Education;
StartupNotify=true
Encoding=UTF-8
X-Deepin-Vendor=rnaseq-tools
DESKTOP

        # ---- info 文件 (UOS 商店规范) ----
        cat > "$INSTALL_ROOT/info" << INFO
{
  "appid": "$APPID",
  "name": "$APP_NAME",
  "version": "${VERSION}.1",
  "arch": ["amd64"],
  "permissions": {
    "autostart": false,
    "notification": false,
    "trayicon": false,
    "clipboard": false,
    "account": false,
    "bluetooth": false,
    "camera": false,
    "audio_record": false,
    "installed_apps": false
  }
}
INFO

        # ---- 构建 ----
        DEB_FILE="${DEB_NAME}_V${VERSION}_amd64.deb"
        dpkg-deb --build "$DEB_BUILD_DIR" "dist/$DEB_FILE"
        rm -rf "$DEB_BUILD_DIR"

        DEB_SIZE=$(du -h "dist/$DEB_FILE" 2>/dev/null | cut -f1 || echo "?")
        echo "  ✓ DEB 包: dist/$DEB_FILE ($DEB_SIZE)"
        echo ""
        echo "  安装: sudo dpkg -i dist/$DEB_FILE"
    fi
fi

# ---- 发布模式 ----
if [ "$RELEASE_MODE" -eq 1 ]; then
    RELEASE_DIR="release-$VERSION"
    mkdir -p "$RELEASE_DIR"
    cp "dist/$APP_NAME" "$RELEASE_DIR/"
    cp "dist/$DEB_FILE" "$RELEASE_DIR/" 2>/dev/null || true
    cp README.md CHANGELOG.md LICENSE VERSION "$RELEASE_DIR/" 2>/dev/null || true
    echo ""
    echo "  ✓ 发布目录: $RELEASE_DIR/"
    echo ""
    echo "  上传到 GitHub Releases:"
    echo "    gh release create v$VERSION \\"
    echo "      --title 'v$VERSION' \\"
    echo "      --notes-file CHANGELOG.md \\"
    echo "      $RELEASE_DIR/*"
fi

echo ""
echo "============================================"
echo "  构建完成!"
echo "============================================"
echo ""
echo "  产物:"
echo "    dist/$APP_NAME           (可执行文件)"
[ "$BUILD_DEB" -eq 1 ] && echo "    dist/$DEB_FILE  (Debian包)"
echo ""
