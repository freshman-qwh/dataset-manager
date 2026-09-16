# 数据集保存视图契约

## 目标

E2A 为本地单用户工作流提供可复用的样本筛选和标注队列。保存视图只记录 SQLite 元数据，不复制、移动、重命名或修改原始文件。

## 持久化内容

每个保存视图归属一个数据集，并冻结：

- 名称；
- 创建时的数据集任务类型；
- 搜索词、文件类型、文件状态、样本标签、split、审核状态和标注进度；
- 排序字段和顺序；
- 队列范围：`current_filter`、`all_pending` 或 `current_split`；
- 创建和更新时间。

不保存当前页码、分页大小、临时勾选样本、当前打开样本或原始文件内容。保存、恢复和删除视图均不递增 dataset revision。

`current_split` 必须同时保存明确的 split。几何标注队列仍只接收可用图片；不可用文件或非图片筛选可以恢复到样本工作区，但不能伪装成可执行的标注队列。

## API

```text
POST   /api/datasets/{dataset_id}/saved-views
GET    /api/datasets/{dataset_id}/saved-views
GET    /api/datasets/{dataset_id}/saved-views/{saved_view_id}
DELETE /api/datasets/{dataset_id}/saved-views/{saved_view_id}
```

- 同一数据集内名称按不区分大小写检查，重复名称返回 `409`。
- 未执行最新迁移时返回 `503`，不会静默创建正式表。
- 视图只能在所属数据集内读取和删除。
- 删除数据集时同步删除保存视图记录。

## 前端恢复语义

“应用视图”显式覆盖当前搜索、筛选和排序，将页码重置为第一页，并清除临时样本选择。“开始队列”按保存的队列范围构建标注页 URL；当任务类型已经变化、当前划分缺失或筛选与几何标注不兼容时，入口禁用并显示原因。

## 范围边界

本切片不提供账户、共享、云同步、团队权限、跨数据集视图或外部 AI 服务。近重复分析和离线 prediction 评估属于后续 E2 切片。
