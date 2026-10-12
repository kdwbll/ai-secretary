SecondBrain 0.8.1：安全与稳定性更新，提供三端安装包。

- Windows：下载 `SecondBrain-Setup-0.8.1.exe`，双击安装，无需 Git 或 Python。
- macOS（15 或更高版本）：Apple Silicon 下载 `SecondBrain-macOS-arm64-0.8.1.dmg`；Intel 下载 `SecondBrain-macOS-x86_64-0.8.1.dmg`，拖入 Applications 后打开。
- Android：下载 `SecondBrain-Android-0.8.1.apk`，安装后在电脑设置页生成配对码。

此次更新修复模型请求失败统计、增加重试退避，并提供 Web/Android 的记忆保存失败提示和重试按钮。桌面安装包包含运行环境、网页和文档处理依赖。关闭浏览器后服务仍在后台运行，可在设置中暂停或终止。

安装提示：
- 桌面应用目前未购买代码签名证书。macOS 如阻止打开，请确认下载来自本仓库后在“系统设置 → 隐私与安全性”中允许打开；Windows 可能显示 SmartScreen 提示。
- Android 是使用当前开发签名的测试版 APK，与此前同签名安装包可覆盖升级。
- Windows 数据保存在 `%LOCALAPPDATA%\SecondBrain`；macOS 数据保存在 `~/Library/Application Support/SecondBrain`。安装包不含个人数据，源码版数据需要自行迁移。
- 更新桌面应用前，先在旧版网页设置中终止服务。
