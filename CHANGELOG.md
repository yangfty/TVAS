# 更新日志

本文档记录「转录组 De Novo 组装分析软件」的所有重要变更。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)。

---

## [0.0.5] - 2026-08-06

### 修复
- 修复 Qt xcb 平台插件缺失导致无法启动
- PyInstaller 增加 `--collect-all PyQt5` 完整打包 Qt 插件
- deb 增加 libxcb 系列系统依赖

---

## [0.0.4] - 2026-08-06

### 修复
- 修复 PyInstaller 打包缺少 `pkgutil` 模块导致启动崩溃 (ModuleNotFoundError)
- 显式打包 pkgutil/importlib 等标准库模块

---

## [0.0.3] - 2026-08-05

### 修复
- 改用 ubuntu-20.04 构建，兼容 UOS 的 glibc 版本

---

## [0.0.2] - 2026-08-04

### 新增
- **自包含 Conda 部署**：首次启动自动下载 Miniconda 到 `~/.local/share/TVAS/`，无需系统预装 Conda
- Conda 优先级：内置 > 本地 > 系统 > 自动下载
- 环境完全隔离，不影响 UOS 系统

### 变更
- 项目更名为 **TVAS**
- deb 包名 `TVAS_V0.0.2_amd64.deb`
- GitHub 仓库: `yangfty/TVAS`

---

## [0.0.1] - 2026-08-04 (内部开发)

### 新增
- 完整的 11 步转录组 de novo 组装分析流程
- PyQt5 图形化桌面界面（三栏布局）
- Conda 虚拟环境自动创建与管理
- 一键安装所有生物信息学软件 (FastQC, Fastp, Rcorrector, Trinity, Jellyfish, CD-HIT, TransDecoder, Gffread, Kallisto)
- 样本表格管理（手动添加 / samples_file 导入）
- 实时彩色日志输出 + 步骤状态指示灯 + 整体进度条
- 后台线程执行（不阻塞界面）
- 配置文件 JSON 保存/加载
- 可调参数：Fastp 质量阈值、CD-HIT 相似度、Trinity 内存、CPU 线程数
- PyInstaller 打包为独立可执行文件
- Debian (.deb) 打包支持
- UOS 应用商店上架规范兼容
- 应用图标（DNA 双螺旋主题）
- 桌面启动器 .desktop 文件
- 辅助脚本：序列重命名、GFF3 重命名、DOS/Unix 格式转换

### 分析步骤
1. FastQC — 原始数据质量评估
2. Fastp — 数据过滤与去接头
3. Rcorrector — RNA-seq reads 纠错
4. Trinity — de novo 转录本组装
5. 提取最长 Isoform — 每个基因保留最长转录本
6. CD-HIT — 聚类去冗余（默认 80% 相似度）
7. 重命名序列 — 规范化命名 + 换行符转换
8. TransDecoder LongOrfs — 识别长开放阅读框
9. TransDecoder Predict — 最终 CDS 预测
10. 重命名 GFF3 — 统一注释文件命名
11. Gffread — 提取 CDS / Protein 序列
