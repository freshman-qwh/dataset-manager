# 旧目录映射：产品交互与技术方案

日期：2026-09-15
状态：已实现，候选版本 `v0.5.0`

## 1. 使用场景与目标

用户已有一批按文件夹整理的图片，例如：

```text
客户批次/
  OK/
  NG/
    划痕/
      严重/
  待复核/
```

图片已经由 Dataset Manager 扫描登记。旧目录映射把这些“目录含义”转换为结构化分拣元数据，之后可以继续在快速分拣工作区复核、筛选和导出。映射只更新 SQLite，不读取目录之外的新文件，不移动、重命名、复制或删除原图。

首版只分析每张图片的直接父目录。例如 `NG/划痕/严重/a.png` 的来源目录是 `NG/划痕/严重`。不提供正则表达式、模糊路径规则或自动创建缺陷类型，避免一条宽泛规则误改大量样本。

## 2. 产品交互

入口位于数据集详情的“管理与导出 → 映射旧目录”，其他操作菜单也提供相同入口。

向导分三步：

1. **映射来源目录**：分页列出目录、图片数、未分拣数、已有判定数和示例路径。每个目录选择“不导入、OK、NG、待定”。
2. **选择已有判定处理方式**：默认“只填未分拣”；用户可显式选择“覆盖已有判定”，界面持续显示风险提示。
3. **预览并导入**：显示将写入、已经一致、保留已有、未映射和文件不可用的数量，以及逐图片来源、目标和处理结果。只有存在实际变化时才能提交后台任务。

“按文件夹名生成草稿”只识别常见 `OK/good/pass`、`NG/bad/defect`、`pending/review` 名称，以及能匹配当前缺陷类型代码/名称和程度的路径片段。草稿不会自动提交。普通 `OK/` 在细分 OK 模式下只填“OK”，仍要求用户明确选择“完全 OK”或“勉强 OK”；系统不会把没有等级的旧 OK 静默当作纯正常样本。

字段随数据集当前分拣层级变化：

- 统一 OK：映射为 OK 时不显示等级。
- 细分 OK：每个 OK 目录必须选完全或勉强。
- NG 不细分：只记录 NG。
- 按类别：可选一个现有且启用的缺陷类型，作为该目录图片的类型和主缺陷。
- 按程度：可选轻微、中等或严重，也允许未评估。
- 类别＋程度：同时提供两个字段。

未映射目录保持不变。文件状态不是正常的图片不写入。已有备注始终保留；覆盖已有判定时，只替换判定、等级、类型、主缺陷和程度。

## 3. 一致性与安全规则

预览在应用存储生成一小时有效的不可变计划，冻结：

- dataset ID、revision 和分拣配置版本；
- 每个样本 ID、相对路径、文件 hash 和 triage version；
- 来源目录、目标分拣字段和预览决策；
- 映射规则、已有判定处理方式和计划内容 hash。

任务参数只保存计划 ID、计划 hash 和变更数量，不把完整样本列表写入 jobs JSON。

创建任务、任务校验和最终写入都会检查计划、dataset revision、配置版本、样本 triage version、文件 hash 和文件状态。任何冲突都要求重新预览。正式写入使用 SQLite `BEGIN IMMEDIATE` 单事务；所有目标再次核对后才写入，任一冲突整批回滚。一次成功导入只提升一次 dataset revision，每个实际变化样本的 triage version 各提升一次。

任务排队时可以取消；开始写事务前再次检查取消状态。为了维持整批原子性，不把正式写入拆成可见的部分成功批次。

## 4. API

| 接口 | 职责 |
|---|---|
| `GET /api/datasets/{id}/triage-directory-sources` | 分页/搜索来源目录，返回数量、示例、当前策略和可用缺陷类型 |
| `POST /api/datasets/{id}/triage-directory-mapping-previews` | 校验映射并生成不可变预览计划 |
| `GET /api/datasets/{id}/triage-directory-mapping-previews/{plan_id}` | 分页读取计划中的逐样本决策 |
| `POST /api/datasets/{id}/triage-directory-mapping-jobs` | 校验计划并创建后台导入任务 |

后台任务类型为 `triage.directory_mapping_import`，沿用任务中心的排队、取消、失败、重试和重启恢复状态。任务中心结果显示写入、保留已有和未映射数量。

## 5. 代码结构

| 位置 | 职责 |
|---|---|
| `backend/app/schemas/triage_directory_mapping.py` | 来源目录、规则、预览、计划引用 schema |
| `backend/app/services/triage_directory_mapping_service.py` | 目录分组、规则校验、预览决策、计划持久化与 hash 校验 |
| `backend/app/services/triage_directory_mapping_job_service.py` | 活动任务去重、二次校验和单事务写入 |
| `backend/app/api/triage_directory_mapping.py` | 四个目录映射 API |
| `backend/app/core/job_runtime.py` | 注册目录映射任务处理器 |
| `frontend/src/components/TriageDirectoryMappingModal.tsx` | 三步映射向导、草稿、预览与任务状态 |
| `frontend/src/types/triageDirectoryMapping.ts` | 前端类型契约 |
| `frontend/src/api/client.ts` | API 客户端 |
| `frontend/src/components/JobCenter.tsx` | 任务阶段与导入结果摘要 |

不新增数据库表或 Alembic 迁移。映射结果直接使用现有 samples 分拣字段与 `sample_defect_links`。

## 6. 验收边界

自动化覆盖：

- 目录分页、搜索、根目录和嵌套目录；
- 细分 OK 缺等级阻断、统一 OK 禁止等级；
- NG 类型和程度映射；
- 默认跳过已有结果并保留备注；
- 显式覆盖、未映射和不可用计数；
- 活动任务去重、排队取消、一次 revision 提升；
- 预览后 dataset 变化、样本版本竞争和不安全相对目录；
- 竞争时整批失败，未冲突样本也不发生部分写入。

人工验收应再覆盖中文目录、目录很多时的分页搜索、草稿后人工修正、刷新任务中心，以及完成后在快速分拣、统计和目录导出中的一致显示。
