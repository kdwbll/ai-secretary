# 第二大脑 · AI 私人助理

一个在自己电脑上运行的中文 AI 助理。长期记忆保存在可读、可编辑、可迁移的 Markdown 文件中；SQLite 只保存索引、队列、配置与审计记录。

## 已实现

- Markdown 记忆初始化、front matter、每日流水和自动索引
- 事实改写、条件/推测标记、全局“忘掉”、修改审计与撤销
- 多供应商 OpenAI 兼容模型路由、主备重试和本地离线降级
- CLI 冷启动采访、对话、搜索、遗忘和撤销
- 中文 Web 工作台：今日简报、对话、记忆浏览器、上传、设置
- 07:30 早报、22:30 复盘、周日整理（Asia/Shanghai）
- 文件哈希去重与按月归档；TXT/CSV/JSON/PDF/Word/Excel/ZIP 提取
- 银行消费、取件码、火车、医疗、账单、验证码和营销短信规则
- Android Compose 工程：系统分享、短信、通知监听、WorkManager 同步基础
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

需要连接 Android 手机时，应先确认当前网络可信，再显式运行：

```bash
.venv/bin/python -m uvicorn core.secretary.app:app --host 0.0.0.0 --port 8765
```

随后在手机中填写电脑的局域网 IP，例如 `http://192.168.1.20:8765`。当前版本尚未实现访问令牌，切勿在公共 Wi-Fi 下启用局域网监听。

Windows PowerShell：

```powershell
py -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m core.secretary.cli init
.venv\Scripts\python -m uvicorn core.secretary.app:app --host 127.0.0.1 --port 8765
```

## CLI

```bash
.venv/bin/python -m core.secretary.cli interview
.venv/bin/python -m core.secretary.cli chat "我下个月要考试，怎么安排复习？"
.venv/bin/python -m core.secretary.cli search "考试"
.venv/bin/python -m core.secretary.cli forget "某项信息"
.venv/bin/python -m core.secretary.cli undo 42
```

## 配置模型

在 Web 的“设置”页选择供应商，填写 `base_url`、API Key 和模型名称。保存后该模型会用于 `fast` 与 `smart` 任务。支持 OpenAI、DeepSeek、通义千问兼容模式、Kimi、智谱、Gemini OpenAI 兼容端点和本地 Ollama。

密钥保存在本机 `data/second-brain.db`，该文件已被 Git 忽略。不要把 API Key 写入代码或提交到仓库。

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

## 测试

```bash
.venv/bin/python -m pytest -q
```

## Android

用 Android Studio 打开 `android/`。高权限数据源必须由用户在手机上明确授权。短信权限在部分应用商店受到严格限制；自行安装场景仍需展示用途说明。当前环境没有 Android SDK/JDK，故仓库内仅完成源码与静态检查，APK 需在 Android Studio 中编译和真机联调。

## 当前边界

- 图片 OCR、视频抽帧、人脸聚类和 Health Connect 需要设备模型/权限，接口位置已预留但尚未做真实设备联调。
- “按意思搜索”当前为本地词法检索；接口可替换为 sqlite-vec。
- 日历写入、二维码配对和完整相册增量同步需在 Android 设备上继续完成。
- 本阶段按规格不做记忆加密；`Storage` 抽象允许后续替换为加密存储。

更详细的取舍见 [docs/decisions.md](docs/decisions.md)。
