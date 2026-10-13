SecondBrain 0.11.0：第三阶段“记忆与性能”正式版。

- 长期记忆使用持久化全文索引；正常对话检索不再遍历或读取全部 Markdown。
- 保存、编辑、撤销和外部单文件变更会增量更新索引。
- 否定、问题、他人转述、计划和不确定事实不再直接写成已确认偏好；需要时在 Web 或 Android 中确认。
- 真实 3000 个 Markdown 发布基准通过：冷建索引约 4.06 秒，热重扫约 142 毫秒，单文件增量更新约 144 毫秒，检索 P95 约 0.31 毫秒。

安装包：

- Windows：`SecondBrain-Setup-0.11.0.exe`，双击安装，无需 Git 或 Python。
- macOS 15+：Apple Silicon 用 `SecondBrain-macOS-arm64-0.11.0.dmg`；Intel 用 `SecondBrain-macOS-x86_64-0.11.0.dmg`。
- Android 9+：`SecondBrain-Android-0.11.0.apk`，沿用此前签名，可直接覆盖升级。

更新前请在旧版网页设置中终止桌面服务。安装包不包含个人数据；Windows 数据位于 `%LOCALAPPDATA%\SecondBrain`，macOS 数据位于 `~/Library/Application Support/SecondBrain`。桌面安装包尚未进行商业代码签名，系统可能提示未认证开发者。数据库已升级至结构版本 10，不要再用旧程序打开升级后的数据。
