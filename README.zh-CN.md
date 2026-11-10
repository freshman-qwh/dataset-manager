# Dataset Manager 中文文档

产品介绍、Windows 便携版和上手流程请从[项目首页](README.md)开始。源码安装与启动见[开发工作流](docs/development-workflow.md)，其他操作见[文档导航](docs/README.md)。

## 数据库维护

便携版用户先从页面安全退出，再用新版 `DatasetManager.exe` 启动。启动器会先备份并校验，再升级需要迁移的数据库。

从源码运行时，如果页面提示工作区需要升级，请先关闭后端及其他数据库使用者。核对页面显示的数据库路径，然后在 `backend` 目录用项目 Python 环境运行以下命令。命令中的路径适用于默认工作区，使用其他工作区时请改为实际路径。

```bash
uv run python -m app.cli.database status --database ../database/app.db
uv run python -m app.cli.database upgrade --database ../database/app.db --backup-dir ../database/backups
```

升级命令先创建并校验备份，再迁移数据库副本。升级成功后重启后端。若命令报告数据库占用或存在 SQLite 侧车文件，请按[迁移与恢复说明](docs/database-migrations.md)处理。
