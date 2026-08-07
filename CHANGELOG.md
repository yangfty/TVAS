# 更新日志

本文档记录「转录组分析软件 TVAS」的所有重要变更。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)。

---

## [0.0.14] - 2026-08-07

### 改进
- **界面布局简化**：
  - 软件包管理主按钮行从 5 个精简为 3 个：「▶ 安装全部软件包」/「✓ 验证安装」/「更多操作 ▾」
  - 「更多操作 ▾」下拉菜单收纳：重装选中 / 卸载选中 / 卸载全部
  - 「高级设置」默认折叠成标题行，标题提示「自定义安装 · 环境终端 · 日志」
  - 主操作按钮加大（安装按钮用主题色突出），提高点击舒适度
  - 整体界面更简洁，常用功能一目了然

---

## [0.0.13] - 2026-08-07

### 新增
- **卸载选中软件包**：选中表格行（可多选）卸载，卸载后清空「已装版本」、状态恢复「未安装」
- **卸载全部（删除环境重建）**：直接删除整个分析环境（最干净，避免 conda 残留依赖），
  之后需重新「创建环境」并安装软件包；删除后表格自动清空、按钮状态复位
- env_manager 新增 `uninstall_package()` 和 `remove_env()`

---

## [0.0.12] - 2026-08-07

### 新增
- **环境终端**（高级设置）：在分析环境中手动执行任意命令
  - 支持 `conda install -c bioconda trinity=2.15`、`which Trinity`、`conda list` 等
  - 同步执行并显示完整输出（超时 2 小时，适合大软件包下载）
  - 执行成功后自动刷新表格中的已装版本
- **安装错误智能分析**：安装失败时自动识别常见错误并给出中文建议
  - UnsatisfiableError 依赖冲突 → 建议装新版/用 mamba/清缓存
  - PackagesNotFoundError → 建议去掉版本号
  - 网络错误 → 建议检查代理/配置国内镜像
  - 磁盘/权限错误 → 对应处理建议

---

## [0.0.11] - 2026-08-06

### 改进
- **布局优化**：环境设置页全部纳入滚动区，窗口小时仍能浏览；软件包表格最小高度 300，日志区最小 200
- **软件包表格新增「类型」列**：
  - 标题改为「软件包安装（★ 为 De Novo 流程必需）」
  - 表格列改为：软件包 / 已装版本 / 类型(★必需或可选) / 状态
  - ★ 必需 红色显示，可选灰色显示
- **版本列改为显示安装后实际版本**（不再预设），安装/重装/验证成功后自动查询 conda list 回填
- **自定义安装的包自动加入表格**：「自定义」蓝色显示，含版本和状态
- 每个 PackageSpec 新增 `required` 和 `description` 字段

---

## [0.0.10] - 2026-08-06

### 新增
- **高级设置面板**（环境设置页底部）：
  - 自定义软件包安装：输入包名（如 salmon / hisat2=2.2.1）自动安装到分析环境
  - conda 完整命令输出日志区（深色终端风格）
  - 「查看选中包日志」：查看指定软件包最近一次安装的完整输出
  - 「查看最近命令输出」：查看最近一次 conda 命令的完整日志
- 所有 conda 操作现在都会记录完整 stdout/stderr，便于定位安装失败原因

---

## [0.0.9] - 2026-08-06

### 修复
- 修复「重装选中软件包」闪退：Qt clicked 信号的 checked 参数被误当成表格项
- 按钮触发改用 lambda 包裹，内部用 isinstance 判断参数类型

---

## [0.0.8] - 2026-08-06

### 新增
- 「↻ 重装选中软件包」按钮：选中表格中的软件包即可单独重装（支持 Ctrl 多选）
- 双击软件包表格行也可快速触发重装

---

## [0.0.7] - 2026-08-06

### 修复
- 修复 CondaToSNonInteractiveError：新版 Miniconda 要求接受 Anaconda 服务条款
- 所有 conda 调用注入 `CONDA_PLUGINS_AUTO_ACCEPT_TOS=true`
- 本地 Miniconda 安装后自动执行 `conda tos accept`

---

## [0.0.6] - 2026-08-06

### 新增 (UI 架构升级)
- **三大分析模块导航**：顶部模块切换栏
  - 模块 1: De Novo 组装（已实现，11 步完整流程）
  - 模块 2: 测序数据比对（占位 — 计划 HISAT2/STAR 比对 + featureCounts 定量）
  - 模块 3: 基因差异表达分析（占位 — 计划 DESeq2/edgeR + GO/KEGG 富集）
- 新增 `ModuleNavBar`：顶部三模块切换条
- 新增 `ModulePlaceholderPage`：开发中模块占位页（含计划步骤说明卡片）
- 关于对话框更新为三大模块概览

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
