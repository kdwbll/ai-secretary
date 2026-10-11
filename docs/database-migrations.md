# 数据库迁移

数据库使用 SQLite 的 `PRAGMA user_version` 保存当前结构版本，并用 `schema_migrations` 表记录已经执行的迁移名称和时间。

## 新增迁移

1. 在 `core/secretary/database.py` 中新增一个迁移函数。迁移必须能够在目标结构已经存在时安全跳过。
2. 将迁移追加到 `MIGRATIONS` 末尾，版本号必须从 1 开始连续递增，不能修改或复用已经发布的版本号。
3. 同步更新 `SCHEMA`，让全新安装直接创建最新结构。
4. 在 `tests/test_database.py` 中增加旧版本升级、数据保留和失败回滚测试。

每个迁移在独立事务中执行。迁移函数、迁移历史记录和 `user_version` 更新会一起提交；任何一步失败都会回滚，并阻止服务继续启动，避免程序在不完整的数据库结构上运行。

## 检查版本

```bash
sqlite3 data/second-brain.db 'PRAGMA user_version; SELECT * FROM schema_migrations ORDER BY version;'
```

不要手动修改 `user_version`，也不要删除 `schema_migrations` 中的记录。
