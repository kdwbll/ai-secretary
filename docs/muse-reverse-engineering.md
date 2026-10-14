# Muse 公开行为与架构逆向报告

日期：2026-10-14
目标：以 Meta Muse 为参照，为“第二大脑”确定可复现的代理能力与安全架构。
范围：仅分析官方公开网页、产品与安全架构说明，以及本项目现有代码；不登录 Muse、不抓取私有流量、不绕过认证或安全机制。

## 证据边界

初版报告只有公开资料，后续已收到用户提供、允许分析的 Android APK。下方“APK 静态证据”记录了可复核的归档与资源层观察；DEX 代码与二进制实现尚未反编译，也没有已登录会话、私有流量或运行时抓包。因此，除明确标为“已观察”的内容外，内部实现仍只作为设计参考，不能声称已验证。

| 编号 | 类型 | 观察 / 结论 | 证据 |
| --- | --- | --- | --- |
| OBS-01 | 公开架构 | 每位用户有独立云端 Linux VM；客户端（Web/iOS/Android）直接连 VM，VM 中有浏览器、工作区、文件与持久状态。 | [Meta 安全架构说明](https://research.meta.ai/blog/security-and-safety-for-ai-agents-our-approach-with-muse) |
| OBS-02 | 公开架构 | 代理运行环境与安全服务分离：代理提出动作，独立 Sentinel 决定允许、拒绝或询问；凭据由独立 auth 服务保存和按需注入。 | [Meta 安全架构说明](https://research.meta.ai/blog/security-and-safety-for-ai-agents-our-approach-with-muse) |
| OBS-03 | 公开架构 | 审批不是聊天文本：审批绑定具体连接器、目标、用途与时限；写入和高风险行为会停止等待用户。 | [Meta 安全架构说明](https://research.meta.ai/blog/security-and-safety-for-ai-agents-our-approach-with-muse) |
| OBS-04 | 公开架构 | 浏览器由独立 broker 控制；浏览子代理拿到的是受控页面可访问性快照，不可在页面中执行任意脚本。登录、人工接管时代理暂停。 | [Meta 安全架构说明](https://research.meta.ai/blog/security-and-safety-for-ai-agents-our-approach-with-muse) |
| OBS-05 | 产品行为 | 目标可在后台长期推进；系统在完成、发现重要变化或需要批准时才打扰用户；主对话之外有项目侧对话、目标与活动视图。 | [Muse 产品设计说明](https://introducing.muse.ai/) |
| OBS-06 | 产品行为 | 除文本外，Muse 会生成可持续使用的 Artifact（如行程、追踪器、学习/消费看板）。 | [Muse 产品设计说明](https://introducing.muse.ai/) |
| OBS-07 | 防御策略 | 邮件中的 OTP、找回密码链接和登录魔链被过滤；外部内容会被标记为不可信，并配合提示注入检测和人工审批。 | [Meta 安全架构说明](https://research.meta.ai/blog/security-and-safety-for-ai-agents-our-approach-with-muse) |

## APK 静态证据（Muse Android 11.0.0.18）

### 样本与方法

- 样本：用户提供的 `/Users/Apple/Downloads/muse-from-meta-11-0-0-18-164.apk`。
- SHA-256：`c86a87132488c5a1b5587af401e3686e7cdf9625a991db655c7cf8feac96ffee`。
- 使用 REA 对 APK 做 ZIP 归档盘点与受控提取；归档证据为 `ev_a3cf12f10051039c73814f291c2de7959b6c64fc91ddacf229355079aff6ca2f`，提取证据为 `ev_24304712afcce7a1a1915bccee07d4e8e35aa34cf6ac1b5520ccbc4b07ab3e36`。
- 未安装或执行 APK。清单有 1,024 个常规文件、5 个 DEX；当前 REA 环境缺少调用方提供的 `jadx-headless-mcp 0.7.1` JAR，故本节不声称已还原 DEX/Manifest 或 native 库的具体实现。

### 已观察到的组件

| 编号 | 静态观察 | 对产品含义的谨慎推断 |
| --- | --- | --- |
| APK-01 | `assets/vmvnc/vnc.html` 与 noVNC 资源存在。其源码注释和桥接代码显示，真实 WebSocket 由 Android 的 `BrowserSessionController` 通过 Tigon 持有 VM bearer；WebView 经 `AndroidVncBridge` 收发 RFB 帧。 | 移动端可呈现并接管远程 VM 的浏览器画面；令牌没有交给网页 JavaScript。这支持“隔离执行环境 + 人工可见/接管”的产品形态，但不证明服务端 VM 的完整架构。 |
| APK-02 | 包含 `assets/docxviewer`、`assets/sheetviewer`、`assets/pptxviewer`。三个查看器均以 URL/ArrayBuffer 加载并经 `AndroidBridge` 报告渲染完成或错误；表格查看器显式处理空工作簿、超大单元格数和密码保护。 | Artifact 不只是聊天文本：客户端有类型化文件预览和明确的成功/失败状态。因此项目应让产物拥有 MIME 类型、版本和渲染状态。 |
| APK-03 | ARM64 原生库名包括 `libagentic_runtime_jni.so`、`libair_executors_jni.so`、`libmcp_server_jni.so`、`MobileMCPRegistryAndroid` 与 `RequestSession`。 | 客户端包中确实集成 Agentic/MCP 相关运行时组件；仅凭库名不能判断模型、工具清单、服务端协议或权限逻辑。 |
| APK-04 | 同时存在远程 VM 视图、文件查看器、五个 DEX 和多套原生库。 | 这是一套较完整的原生客户端能力面，不宜将“类似 Muse”误解为单一聊天页或一次性自动化脚本。 |

### 对本项目排期的直接调整

1. **v0.15 Artifact**：为每个产物保存 `kind`、MIME 类型、来源、版本、渲染状态和失败原因；先实现 `docx/xlsx/pptx/pdf/html` 的安全预览入口，不能把外部 URL 直接交给前端浏览器加载。
2. **v0.17 隔离浏览器**：运行会话需提供截图/活动时间线与“查看并停止”入口。初版不必实现 VNC；预留 `execution_session` 资源模型，后续如做交互接管，由服务端网关持有短期凭据，浏览器页面只接收受控帧流，绝不暴露 bearer token。
3. **v0.14 策略层**：文件预览、下载、上传和跨域跳转同样是动作，不因其看似是 UI 功能而绕过审批与审计。

### 深入验证所需的下一项材料

要继续核对客户端 API、离线队列、权限声明和审批状态机，需要为 REA 提供 `jadx-headless-mcp 0.7.1` JAR 后再解码 DEX。该 JAR 不由 REA 自动下载；在收到用户提供的文件或明确授权从官方上游下载前，不进行下载或反编译配置变更。

## 与现有项目的差距

| 能力域 | 当前项目已具备 | 与 Muse 的关键缺口 | 建议实现 |
| --- | --- | --- | --- |
| 数据与记忆 | 本地 Markdown、SQLite 索引、候选记忆确认、忘记/撤销 | 没有把记忆、事件与目标关联成长期工作上下文 | `goals/tasks/task_runs/task_events` 数据模型；每个输出关联来源与目标。 |
| 事件输入 | 邮件 IMAP、短信、通知、日历、健康、文件 | 事件只被展示或用于对话，没有订阅和任务推进机制 | 规范化事件总线，提供去重键、来源可信度、订阅规则、重放策略。 |
| 后台工作 | APScheduler 的报告/同步任务 | 没有可恢复的用户任务运行记录、锁、执行预算或任务状态 | 以数据库为真相源的任务运行器；调度器只负责唤醒，不保存任务状态。 |
| 权限控制 | 本地浏览器 token、Android 配对 token、服务开关 | 不能对“某个动作”做最小授权，也没有审批实体 | 独立 `policy/approval` 层，动作必须先经服务端校验，不能由模型文字决定。 |
| 凭据与连接器 | API Key 本地保存、IMAP 授权码 | 连接器权限范围、读写分离、撤销与密钥最小暴露不足 | 使用 OS Keychain 或现有加密密钥封装的凭据仓；连接器只收代理令牌或服务端代调用。 |
| 浏览器代理 | 无 | 通用浏览器自动化极易将不可信网页、私有数据和外发行为放在同一执行上下文 | 后置实现：隔离 profile/工作区、域名策略、只读默认、审批/接管、步骤证据包。 |
| 用户体验 | 今日、聊天、记忆、收件箱、健康、设置 | 看不到“助手正在替我推进什么”和“我现在需要批准什么” | 首页三栏：下一步、运行中、待审批；任务详情显示计划、日志、证据与停止按钮。 |

## 可复现架构：本机版 Sentinel

不应直接复刻 Meta 的 VM、eBPF 或内核级污点追踪。本项目可用更小、可维护的本机边界实现同一原则：模型永远不拥有执行权限，执行器永远不绕过策略服务。

```text
Web / Android
    │  创建目标、查看状态、批准动作
    ▼
FastAPI 目标与任务 API ──► SQLite（目标、任务、运行、审计、审批）
    │                                 ▲
    ▼                                 │
Planner（模型或确定性规则）── 动作提案 ─┘
    │
    ▼
Policy / Approval Service  ←── 用户授权、连接器 scope、预算、域名策略
    │ allow / deny / ask
    ▼
受控执行器 ──► 只读连接器 / 写入连接器 / 隔离浏览器
    │                          │
    └──► 事件、Artifact、证据包 ─┘
```

### 不可绕过的实现规则

1. 模型输出只能是 `ActionProposal`，包括动作类型、资源、参数摘要、理由与来源；不得直接执行 Python 函数、Shell 命令或 HTTP 请求。
2. 所有执行入口都在服务端再次调用 `PolicyService.authorize()`；UI、模型与任务调度器都不能跳过它。
3. 外部内容（邮件正文、网页、附件、通知）必须携带 `untrusted=true`；不得把其中的指令当作系统/用户指令。
4. 默认只读；`write`、`irreversible`、敏感数据外发、跨域跳转、文件上传与支付必须生成独立审批记录。
5. 审批绑定 `task_id + connector + resource + 参数摘要 + 过期时间`；批准一次不等于以后任意同类操作都可执行。
6. 凭据仅由连接器层读取。模型、聊天记录、运行日志、浏览器可访问性快照和错误消息不得包含明文 token/密码/OTP。
7. 任何长运行任务都应具有最大运行时长、最大重试数、并发上限、域名 allowlist 与立即停止开关。

## 立即可执行的 v0.12 技术拆分

| 优先级 | 工作项 | 文件/模块建议 | 验收测试 |
| --- | --- | --- | --- |
| P0 | 增加数据库迁移和任务实体 | `core/secretary/database.py`；新建 `goals.py` | 创建/编辑/暂停/完成/取消、迁移备份、重启恢复。 |
| P0 | 增加 `ActionProposal`、`Approval`、`AuditEvent` 类型 | 新建 `core/secretary/actions.py` | 写入动作在无批准时被拒绝；批准过期或参数变化后重新审批。 |
| P0 | 为任务新增 API | `core/secretary/app.py` | 本机 token 与 Android token 均受现有鉴权保护；不能越权读取/改写任务。 |
| P0 | 目标页面及待审批卡 | `web/index.html`、`web/app.js`、Android Compose | 用户能看到下一步、阻塞原因、批准/拒绝后的状态变化。 |
| P1 | 将 APScheduler 改为唤醒器 | `core/secretary/app.py`、新建 `runner.py` | 服务重启不重复运行；同一幂等键的任务只产生一次有效结果。 |
| P1 | 为邮件/日历/通知写事件适配器 | `service.py`、`connectors.py` | 重放历史事件不重复创建待办；未知或恶意文本仅记录，不会触发写操作。 |

## 后续调查清单

以下问题需要用户提供合法可分析的产物或已登录会话后，才能用 REA 做进一步验证：

- Muse Android APK/IPA 或桌面安装包：核对客户端 API、离线队列、数据缓存与权限声明。
- 用户自己导出的 HAR：分析网络动作类型、轮询/推送、审批状态机与错误恢复；不包含密码、令牌或私密内容。
- 已登录但用户拥有的 Muse 浏览器标签：仅被动观察公开 UI 流程，例如目标创建、审批卡、活动视图与浏览器接管。

在未获得这些材料前，不推断私有 API、网络协议、模型提示词、加密实现、反滥用机制或未公开连接器。
