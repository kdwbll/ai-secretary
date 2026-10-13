SecondBrain 0.8.2：第三阶段“记忆与性能”更新。

- 改进否定与条件识别：“我不去游乐场”保留为否定陈述，问题和他人说法不当作本人偏好。
- 不确定、计划和一次经历进入待确认区，Web 与 Android 提供“确认保存 / 不保存”按钮；确认前不进入长期档案。
- 改用增量全文索引：对话不再遍历所有 Markdown 或重复重建索引，应用内修改立即生效，外部修改在后台约 15 秒内更新。
- 数据库自动升级到迁移 10，保留原始 Markdown 与历史对话。

下载与安装：
- Windows：`SecondBrain-Setup-0.8.2.exe`，双击安装，无需 Git 或 Python。
- macOS 15+：Apple Silicon 用 `SecondBrain-macOS-arm64-0.8.2.dmg`；Intel 用 `SecondBrain-macOS-x86_64-0.8.2.dmg`，拖入 Applications。
- Android 9+：`SecondBrain-Android-0.8.2.apk`，使用此前同一测试签名，可覆盖升级。

更新前先在旧版网页设置中终止桌面服务。安装包不包含个人数据；Windows 数据在 `%LOCALAPPDATA%\SecondBrain`，macOS 数据在 `~/Library/Application Support/SecondBrain`，源码版数据需要自行迁移。桌面包尚未购买代码签名证书，系统可能提示未认证开发者。数据库升级后请使用 0.8.2 或更高版本，旧程序不能读取新的数据库版本。
