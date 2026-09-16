# SQLite 正式迁移、备份与恢复

日期：2026-07-26

## 目标与边界

Dataset Manager 使用 Alembic 管理 SQLite 元数据 schema。迁移工具只处理数据库中的数据集、样本、标签、标注和训练准备等元数据，不读取或复制原始数据文件，也不在原始数据目录写入 sidecar。

为了避免应用启动时静默改动唯一实际数据库，F2-0 的迁移采用显式维护命令：

- `status` 只读检查当前版本和唯一 head。
- `backup` 使用 SQLite backup API 创建一致性在线备份，并运行 `PRAGMA quick_check`。
- `upgrade` 仅接受显式数据库路径，要求目标库离线，先备份、再迁移临时副本、最后原子替换。

## 命令

在 `backend` 目录运行：

```bash
python -m app.cli.database status --database ../database/app.db
python -m app.cli.database backup --database ../database/app.db --backup-dir ../database/backups
python -m app.cli.database upgrade --database ../database/app.db --backup-dir ../database/backups
```

`status` 与 `backup` 可以在后端运行时执行。`upgrade` 前必须停止后端和其他数据库使用者；若检测到初始 `-wal`、`-shm`、`-journal` 或数据库占用，命令会拒绝升级。

## 升级顺序

1. 解析目标数据库绝对路径并确认离线。
2. 读取当前 revision；已到 head 时直接返回 `changed: false`。
3. 对已有用户表的数据库创建 SQLite 在线备份并执行 `quick_check`。
4. 从备份创建同目录迁移临时库；全新数据库则创建空临时库。
5. 在临时库运行 Alembic、WAL checkpoint、`quick_check` 和 head revision 校验。
6. 再次确认目标库没有写事务，拒绝任何非空未 checkpoint WAL。
7. 原子替换目标数据库；清理只属于迁移临时库的文件。

任何第 5 步之前或期间的失败都不会修改目标库。第 6 或第 7 步失败时也不会用未验证的临时库覆盖目标库。

## 基线 revision

F2-0 基线 revision 为 `20260726_0001`；F2-1A 新增 jobs 后，当前唯一 head 为 `20260726_0002`：

- 空数据库会创建当前 SQLModel 表和索引。
- 已对齐但没有 `alembic_version` 的数据库会采用当前基线。
- 已知历史数据库会补齐 datasets、samples、tags 和 annotations 的兼容列，并执行已有工作流语义回填。
- `20260726_0002` 只创建 jobs 表与索引；应用启动兼容逻辑不会代替该 migration 创建 jobs。
- 基线不提供破坏性 downgrade。需要回退时恢复升级命令生成的已验证备份。

## 恢复

若升级失败，命令错误会保留原目标库，并在已创建备份时保留备份文件。恢复前：

1. 停止后端与所有 SQLite 使用者。
2. 保留失败数据库用于诊断，不直接覆盖唯一副本。
3. 对备份运行 `PRAGMA quick_check`，确认结果为 `ok`。
4. 将验证过的备份复制到新的恢复路径，先用 `status` 和测试环境启动验证。
5. 只有数据所有者确认核心记录与业务流程后，才替换实际元数据库。

不要删除或改写原始数据目录。元数据库恢复只影响应用维护的元数据。

## F2-0A 实际副本演练

2026-07-26 对实际数据库执行在线 backup，随后只升级该备份副本：

- revision：`None → 20260726_0001`
- datasets：`5 → 5`
- samples：`20,933 → 20,933`
- tags：`53 → 53`
- sample_tag_links：`34 → 34`
- annotation_classes：`10 → 10`
- annotations：`45 → 45`
- training_readiness_states：`1 → 1`
- 升级前后 `quick_check`：`ok`

实际源数据库没有执行 migration，历史孤立元数据也没有被删除；其报告、修复预览和显式确认属于 F2-0B。

## 完整性报告与显式修复

数据集列表的“数据库维护”入口和以下 API 提供 F2-0B 能力：

```text
GET  /api/system/database-integrity
POST /api/system/database-integrity/repair-preview
POST /api/system/database-integrity/repair
```

只读报告覆盖：

- `PRAGMA quick_check` 与 `PRAGMA foreign_key_check`
- 当前 Alembic revision 和唯一 head
- 当前 SQLModel schema 缺失的表或列
- 无所属数据集的 sample、annotation class、tag 和训练准备记录
- 无所属样本或数据集的 annotation
- 缺失 sample/tag 的关联表记录
- annotation 的失效 class/tag 引用
- tag 的缺失或跨数据集父级引用

修复默认不选择。只有数据库已经到达 migration head 时，用户才能选择动作并生成预览。预览返回基于当前问题 ID 和数量生成的 report token 与动态确认文本；执行时会再次检查 token，先创建在线 SQLite 备份，再复核 token，最后在一个事务中按依赖顺序修复。任何变化、确认不一致、备份或事务失败都会拒绝返回成功。

2026-07-26 对实际数据库只运行报告：`quick_check=ok`，发现 1 条 `annotation_classes.id=10` 缺少所属数据集，并产生 1 条外键违规。实际库尚未登记 `20260726_0001`，因此状态为“需要维护”，未生成修复预览、未创建修复备份、未删除该记录。
