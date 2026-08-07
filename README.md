# RNA-seq De Novo Assembly GUI

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-UOS%20%7C%20Debian%20%7C%20Ubuntu-blue)]()

> **转录组测序数据 De Novo 组装分析桌面软件**  
> 基于 PyQt5 + Conda，为没有参考基因组的物种（如朱顶红）提供一站式转录组组装方案

<p align="center">
  <img src="screenshots/main_window.png" alt="主界面" width="700">
</p>

## 特性

- **图形化界面** — PyQt5 桌面应用，无需命令行操作
- **一键环境搭建** — 自动创建 Conda 虚拟环境并安装所有生物信息学软件
- **完整分析流程** — 11 步标准 de novo 转录组组装流程
- **实时监控** — 彩色日志输出、步骤状态指示灯、整体进度条
- **后台执行** — 多线程不阻塞界面，支持随时停止
- **参数可调** — Fastp 质量阈值、CD-HIT 相似度、Trinity 内存等均可配置
- **配置持久化** — 支持 JSON 配置文件保存/加载
- **打包分发** — PyInstaller 打包为独立可执行文件，无需安装 Python 环境

## 分析流程

```
原始 FASTQ 数据
    │
    ▼
[1] FastQC ──────── 质量评估
    │
    ▼
[2] Fastp ───────── 数据过滤 (去接头、低质量)
    │
    ▼
[3] Rcorrector ──── RNA-seq 错误纠正
    │
    ▼
[4] Trinity ─────── de novo 转录本组装
    │
    ▼
[5] 提取最长Isoform ─ 每个基因保留最长转录本
    │
    ▼
[6] CD-HIT ──────── 聚类去冗余 (默认 80%)
    │
    ▼
[7] 重命名序列 ──── 规范化命名 + DOS→Unix
    │
    ▼
[8] TransDecoder ── LongOrfs (识别ORF)
    │
    ▼
[9] TransDecoder ── Predict (预测CDS)
    │
    ▼
[10] 重命名GFF3 ─── 统一注释命名
    │
    ▼
[11] Gffread ────── 提取 CDS / Protein 序列
    │
    ▼
  最终输出: CDS.fasta + PEP.fasta
```

## 依赖环境

| 软件 | 版本 | 用途 |
|------|------|------|
| FastQC | 0.11.x | 测序数据质量评估 |
| Fastp | latest | 数据过滤与接头去除 |
| Rcorrector | latest | RNA-seq reads 错误纠正 |
| Trinity | 2.8.x | de novo 转录本组装 |
| Jellyfish | 2.2.x | K-mer 计数 (Trinity 依赖) |
| CD-HIT | 4.8.x | 序列聚类去冗余 |
| TransDecoder | 5.5.x | CDS 编码区预测 |
| Gffread | latest | GFF3 序列提取 |

> 所有生物信息学工具通过 Conda 自动安装，无需手动配置。

## 安装

### 方式一：从源码运行

```bash
# 克隆仓库
git clone https://github.com/yangfty/TVAS.git
cd TVAS

# 安装 PyQt5
pip install PyQt5 --user

# 启动
chmod +x run.sh
./run.sh
```

### 方式二：下载打包版本（推荐给同事使用）

1. 前往 [Releases](https://github.com/yangfty/TVAS/releases) 页面
2. 下载最新的 `TVAS_V*.deb` 安装包
3. 双击安装，或在终端运行：

```bash
sudo dpkg -i TVAS_V*.deb
```

安装后在应用程序菜单搜索 **「转录组DeNovo组装」**，点击图标即可启动。

### 方式三：UOS 应用商店

在统信 UOS 应用商店搜索「转录组DeNovo组装」安装。

## 自行打包

```bash
# 1. 打包为独立可执行文件
./build.sh

# 2. 打包为 .deb 安装包 (用于分发/商店上架)
./build.sh --deb
```

## 使用说明

### 1. 环境设置
- 检测 Conda → 创建虚拟环境 → 一键安装所有生物信息学软件

### 2. 样本配置
支持两种方式：
- 手动填写样本表格（条件组 / 重复名 / R1路径 / R2路径）
- 导入已有的 Trinity samples_file 格式文件

### 3. 参数配置
- **物种前缀**：如 `Hvi`（朱顶红 Hippeastrum vittatum）
- **基因前缀**：如 `Uni`（Unigene）
- **CPU 线程数**
- **Trinity 最大内存**
- **Fastp 质量/长度阈值**
- **CD-HIT 相似度阈值**

### 4. 执行流程
点击 **「运行全部流程」**，等待自动完成 11 个步骤。

## 项目结构

```
TVAS/
├── main.py                     # 程序入口
├── run.sh                      # 开发模式启动脚本
├── build.sh                    # PyInstaller + deb 打包脚本
├── requirements.txt            # Python 依赖
├── rnaseq_app/
│   ├── config.py               # 配置管理
│   ├── env_manager.py          # Conda 环境管理
│   ├── steps.py                # 11 个分析步骤
│   ├── pipeline.py             # 流程编排 + 后台线程
│   ├── main_window.py          # PyQt5 主界面
│   └── resources/              # 图标、desktop 文件
├── scripts/                    # 辅助脚本 (序列/GFF3 重命名)
├── debian/                     # Debian 打包规范
└── uos/                        # UOS 商店上架材料
```

## 贡献

欢迎提交 Issue 和 Pull Request。

## 许可证

[MIT License](LICENSE)

---

**适用平台**: UOS 专业版/社区版 · Debian 10+ · Ubuntu 20.04+  
**开发者**: 见 [GitHub Contributors](https://github.com/yangfty/TVAS/graphs/contributors)
