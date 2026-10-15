# 第二大脑 · AI 私人助理

一个在自己电脑上运行的中文 AI 助理。长期记忆保存在可读、可编辑、可迁移的 Markdown 文件中；SQLite 只保存索引、队列、配置与审计记录。

普通用户请参阅 [v0.15.0 用户手册](docs/user-manual-v0.15.0.md)，其中包含三平台安装、手机配对、行动与 Artifact、安全边界及故障排查。

## 已实现

- Markdown 记忆初始化、front matter、每日流水和自动索引
- 事实改写、条件/推测标记、全局“忘掉”、修改审计与撤销
- 多供应商 OpenAI 兼容模型路由、按次选择模型、文字/图片/视频独立路由、主备重试和本地离线降级
- CLI 冷启动采访、对话、搜索、遗忘和撤销
- 中文 Web 工作台：今日简报、对话、记忆浏览器、上传、设置
- 本地聊天记录：按条查看和删除，并可选择同时清理该条对话写入的关联记忆
- 07:30 早报、22:30 复盘、周日整理（Asia/Shanghai）
- 文件哈希去重与按月归档；TXT/CSV/JSON/PDF/Word/Excel/ZIP 提取；图片视觉分析和视频关键帧分析
- 银行消费、取件码、火车、医疗、账单、验证码和营销短信规则
- Android Compose 伴侣：联通状态、双端实时会话、系统分享、短信/通知记录、图片/视频/文件上传与删除、WorkManager 离线队列
- QQ/163 等通用 IMAP 只读连接器（使用邮箱授权码）

## 快速开始

macOS / Linux：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m core.secretary.cli init
./run.sh
```

然后打开 [http://localhost:8765](http://localhost:8765)。默认只允许本机访问，避免未认证的个人记忆暴露到局域网。

macOS 也可以直接双击项目中的 `start-second-brain.command`。启动器会复用已经运行的服务；未运行时会在后台启动，然后自动打开浏览器。手机需要连接时，启动器默认监听可信局域网地址。

需要连接 Android 手机时，应先确认当前网络可信，再显式运行：

```bash
.venv/bin/python -m uvicorn core.secretary.app:app --host 0.0.0.0 --port 8765
```

随后在电脑 Web 的“设置 → 设备安全”生成一次性 6 位配对码。在手机中填写电脑的局域网 IP（例如 `http://192.168.1.20:8765`）和配对码。配对成功后，手机会使用独立设备令牌访问；可随时在电脑端撤销。数据库只保存令牌的 SHA-256 哈希，不保存可直接使用的原令牌。仍不建议把 8765 端口直接映射到公网。

## CLI

```bash
.venv/bin/python -m core.secretary.cli interview
.venv/bin/python -m core.secretary.cli chat "我下个月要考试，怎么安排复习？"
.venv/bin/python -m core.secretary.cli search "考试"
.venv/bin/python -m core.secretary.cli forget "某项信息"
.venv/bin/python -m core.secretary.cli undo 42
```

## 配置模型

在 Web 的“设置”页可以保存、删除多个供应商及其模型，然后分别为“文字处理”“图片处理”“视频处理”选择默认模型。删除正在使用的供应商时，对应路由会被清空，但其他供应商不受影响。对话页顶部还可以仅为本轮临时换模型。支持 OpenAI、DeepSeek、通义千问兼容模式、Kimi、智谱、Gemini OpenAI 兼容端点和本地 Ollama。

图片处理模型必须支持 OpenAI 兼容的 `image_url` 多模态消息。视频上传后先在本机用 FFmpeg 抽取最多 6 个关键帧，再发送给视频模型；未设置视频模型时自动使用图片模型。

密钥保存在本机 `data/second-brain.db`，该文件已被 Git 忽略。不要把 API Key 写入代码或提交到仓库。

每个供应商模型都可以单独设置输入价、输出价和币种，单位为“每百万 Token”。美元价格按设置页中的可编辑汇率换算成人民币；保存价格或汇率后，历史调用费用也会重新计算。内置参考价仅用于估算：DeepSeek 官方直连的 `deepseek-flash` 使用高峰时段、缓存未命中的保守价格，豆包 `doubao-seed-2.1-lite` 使用在线低延迟文本价格。最终费用以供应商账单为准。

## 图片、视频与文档

打开 Web 的“收件箱”或 Android App 的“文件”页，可一次选择多个文件。两个设备共享上传记录；删除记录时会同时删除电脑中的归档原件。所有原件保存到 `files/YYYY-MM/` 并按 SHA-256 去重：

- 图片：缩放到最长边 1600 像素后交给“图片处理”模型。
- 视频：原视频不上传；本机抽取最多 6 个关键帧后交给“视频处理”模型。
- PDF、Word、Excel、CSV、文本和 ZIP：优先在本机提取内容。

同一图片或视频上传成功后仍会去重并显示上次结果；如果上次因为模型配置错误而失败，再次上传会自动使用当前模型重试。也可以点击“使用当前模型重新分析”主动重跑，而不必修改或复制原文件。

## 联网搜索

“设置 → 联网搜索”可以开启按需搜索。只有明确要求搜索，或问题依赖新闻、现任信息、实时价格、优惠、股价、汇率等最新数据时，问题才会发送给搜索服务；普通聊天、个人记忆与文件分析不会自动联网。

支持两种方式：

- 博查 Web Search API（中国大陆推荐）：在 [博查开放平台](https://open.bochaai.com/) 创建 API Key；密钥只在本机加密保存，由后端请求中文网页搜索接口；
- 自托管 SearXNG：填写自己的实例地址，实例需要在配置中允许 JSON 输出。

回答会显示来源链接。搜索结果只是标题和摘要，价格、库存、团购优惠和新闻可能随时变化，应打开原网页复核。联网搜索不绕过网站登录、验证码、付费墙或反爬限制，也不代表能读取美团、大众点评等平台未公开的实时内部数据。

## 聊天记录与动画

对话页的“聊天记录”会显示最近的一问一答。删除某一条时，可以选择只删除聊天记录，或同时删除该条对话写入的每日日志和事实；后者只匹配该条对话的内部编号，不会按关键词批量删除。等待回复采用轻量的 Codex 风格连续动画，回答落定时平滑切换，并自动尊重系统的“减少动态效果”设置。

## 邮件与短信

邮件：在“设置 → 邮件”中填写 IMAP 地址、邮箱账号和邮箱授权码。QQ 邮箱使用 `imap.qq.com:993`，163 使用 `imap.163.com:993`。系统每 30 分钟以只读方式同步未读邮件，也可以手动同步。支持纯文本、HTML、日历、联系人卡片和转发邮件正文；邮件附件会进入统一文件归档，可读取 TXT、Markdown、CSV、JSON、YAML、XML、HTML、ICS、VCF、RTF、EML、PDF、DOC/DOCX、XLSX/XLSM、PPTX、ODS 和 ZIP，并可处理已支持的图片、视频。升级后可点击“重读近期 20 封”补全旧同步记录的正文，不会重复创建邮件历史。请勿填写邮箱登录密码。

短信与通知：由 Android 伴侣 App 在用户明确授权后采集，通过 WorkManager 离线排队并携带设备令牌同步到电脑。电脑端需要在可信局域网中以 `--host 0.0.0.0` 启动；配对码 5 分钟有效、仅可使用一次，连续输错 10 次会立即失效。

## 目录

```text
core/       Python 核心服务、CLI、解析器与提示词
web/        无构建依赖的本地 Web UI
android/    Kotlin + Jetpack Compose 伴侣应用
memory/     用户 Markdown 记忆（默认不纳入 Git）
files/      原始文件归档（默认不纳入 Git）
inbox/      电脑收件箱目录
docs/       设计决策
examples/   不含真实个人信息的演示数据
tests/      核心单元测试
```

## 健康数据

Web 左侧的“健康”页会在本机展示最近 14 天的步数、心率、睡眠、体重、活动能量和距离趋势。支持导入：

- Apple 健康导出的 XML 或 ZIP；
- 小米运动健康 / Mi Fitness 导出的 ZIP、CSV 或 JSON；
- 包含日期及常见健康字段的通用 CSV/JSON。

重复导入会按样本内容去重。健康原始数据只写入本机 SQLite，连接状态摘要写入 `memory/health.md`。图表用于个人记录，不构成医疗建议。

收件箱下方同时提供邮件、短信和通知的可筛选时间线，可追溯每条采集记录的时间、来源与分类。

## 测试

```bash
.venv/bin/python -m pytest -q
```

## Android

用 Android Studio 打开 `android/`，也可以使用仓库自带的 Gradle Wrapper 构建。高权限数据源必须由用户在手机上明确授权。短信权限在部分应用商店受到严格限制；自行安装场景仍需展示用途说明。红米/HyperOS 的完整安装、连接和后台权限步骤见 [docs/android-xiaomi.md](docs/android-xiaomi.md)。

## 当前边界

- 图片和视频分析依赖所选模型的视觉能力；视频当前采用关键帧，不包含音轨转写。
- 人脸聚类、Health Connect、完整相册扫描仍需要真实 Android 设备权限与联调。
- “按意思搜索”当前为本地词法检索；接口可替换为 sqlite-vec。
- 日历写入、二维码扫描配对（当前已支持输入 6 位配对码）和完整相册增量同步需在 Android 设备上继续完成。
- 本阶段按规格不做记忆加密；`Storage` 抽象允许后续替换为加密存储。

更详细的取舍见 [docs/decisions.md](docs/decisions.md)。

## 许可证

本项目采用 [Apache License 2.0](LICENSE) 授权。Copyright © 2026 kdwbll。
