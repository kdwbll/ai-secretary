# SecondBrain 0.12.0：目标与任务内核

本版本开始将“一次对话”变为可持续推进的本地目标。

## 已交付

- 本地 SQLite 新增 `goals`、`tasks`、`task_runs`、`task_events`，并在已有受管数据库升级前保留一致性备份。
- 目标支持创建、编辑、暂停、恢复、完成和取消；任务支持创建、编辑和状态推进。
- 创建请求支持 `X-Idempotency-Key`，网络重试不会重复生成目标或任务。
- 每次创建、修改和状态变更都写入可查询的审计事件。
- Web 端新增“目标”工作区：可新建目标、添加下一步、推进任务、暂停/完成/取消并查看活动记录。
- Android 端新增“目标”标签：可查看同步进度、创建目标、推进任务、暂停/恢复/完成目标。
- 所有新接口沿用已有本机/已配对设备鉴权及暂停服务保护。

## API 摘要

- `GET/POST /api/goals`
- `GET/PUT /api/goals/{goal_id}`
- `POST /api/goals/{goal_id}/status`
- `GET /api/goals/{goal_id}/events`
- `POST /api/goals/{goal_id}/tasks`
- `PUT /api/tasks/{task_id}`
- `POST /api/tasks/{task_id}/status`

## 验证

`116 passed`：覆盖迁移、升级前备份、状态机、幂等创建、审计记录、认证 API 与既有回归测试。

## 尚未进入本版本

后台任务执行器、周期调度、重试/退避与 Android 的任务编辑/活动记录完善属于 v0.13 及后续工作；本版本已预留 `task_runs` 数据结构，但不会静默执行任务。
