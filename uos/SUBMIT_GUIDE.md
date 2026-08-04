# UOS 应用商店上架指南

## 前置准备

### 1. 注册开发者账号

1. 访问 [统信UOS生态网站](https://www.chinauos.com)，注册账号
2. 完成企业/个人开发者认证
3. 登录开发者平台 [store.chinauos.com](https://store.chinauos.com) 或 [appstore-dev.uniontech.com](https://appstore-dev.uniontech.com)

### 2. 准备上架材料

在上架前需准备好以下材料：

| 材料 | 要求 |
|------|------|
| **deb 安装包** | 见下方「构建 deb 包」 |
| **应用图标** | PNG/SVG, 96x96 ~ 512x512px |
| **应用截图** | 3-6 张 JPG/PNG，展示主要界面 |
| **自测试报告** | 功能测试、兼容性测试结果 |
| **用户手册** | 应用使用说明 |
| **应用描述** | 中文和英文版本 |

### 3. 修改 AppID

将 `uos/info` 和所有文件中的 `org.horticulture.rnaseq-denovo` 替换为你的 AppID。
推荐使用你拥有的域名倒置，如 `com.yourdomain.rnaseq-denovo`。

## 构建 deb 包

```bash
# 1. 先打包独立可执行文件
./build.sh

# 2. 构建 deb 包
./build.sh --deb

# 输出: dist/TVAS_V0.0.2_amd64.deb
```

## 提交上架

1. 登录 [store.chinauos.com](https://store.chinauos.com)
2. 进入「应用服务」→「我的应用」→「+新增应用」
3. 填写应用信息：
   - **应用名称**: 转录组DeNovo组装
   - **应用分类**: 科学/生物
   - **上传软件包**: 选择 `.deb` 文件
   - **适配架构**: amd64
4. 上传图标、截图等素材
5. 提交审核（3-5 个工作日）
6. 审核通过后应用将推送到商店

## 版本更新

每次更新版本时：

1. 修改 `VERSION` 文件
2. 更新 `CHANGELOG.md`
3. 更新 `debian/changelog`
4. 更新 `uos/info` 中的 `version` 字段
5. 运行 `./build.sh --deb` 生成新版本 deb 包
6. 在开发者后台「更新」已上架应用的安装包

## 注意事项

- **包名唯一性**: 应用名称在商店中必须唯一
- **禁止系统修改**: deb 包的 postinst 等脚本不能修改系统文件
- **安装路径**: 必须安装在 `/opt/apps/${appid}/` 下
- **目前仅支持免费应用**: 收费功能需与统信线下沟通
- **多架构**: 如需支持龙芯/申威等架构，需分别打包
