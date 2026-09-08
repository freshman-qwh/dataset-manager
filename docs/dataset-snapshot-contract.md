# 数据集轻量快照契约

## 目标与边界

轻量快照把一个明确 `Dataset.revision` 下的训练相关 SQLite 元数据固化为不可变 JSON，用于后续差异比较和训练标签重建。快照不复制图片、视频或其他原始文件，不向数据集根目录写入 sidecar。

数据库表只保存索引信息：dataset id、来源 revision、名称、创建时间、查询范围、导出配置、数量摘要、产物相对路径和内容 SHA-256。完整内容写入应用 `storage/snapshots/dataset-{id}/`。

## 冻结内容

- 数据集身份、资料、任务类型、根路径引用和来源 revision。
- 规范化查询范围与排序；显式样本 ID 会去重排序。
- 每个命中样本的路径引用、文件大小/hash/状态、split、审核与标注进度、备注、自定义元数据和样本标签。
- 标注对象的类别、几何、属性、flags、分组、层级、锁定/隐藏、来源和备注。
- 完整标签目录、标注类别目录、导出格式、空样本选项和 class map。
- detection/segmentation 的默认 class map 来自选中标注类别；classification 来自选中样本标签。名称排序决定稳定 ID。

## 一致性与可复现性

创建开始时记录 dataset revision，内容构建完成后通过条件 `INSERT ... SELECT` 原子校验最新 revision。若构建期间发生元数据写入，发布返回 409，不写快照记录或残缺产物。

`content_sha256` 对不含快照 ID、名称和创建时间的规范化内容计算。因此同一 revision、查询与导出配置重复创建可以有不同记录名称和时间，但内容 hash 必须一致。快照创建是派生行为，不递增 dataset revision。

读取内容时重新计算 SHA-256 并与数据库记录及文档声明交叉校验；产物缺失、损坏或被篡改时返回 410。

## API

- `POST /api/datasets/{id}/snapshots`：按请求范围创建快照。
- `GET /api/datasets/{id}/snapshots`：按时间倒序列出快照。
- `GET /api/datasets/{id}/snapshots/{snapshot_id}`：读取快照索引详情。
- `GET /api/datasets/{id}/snapshots/{snapshot_id}/content`：读取并校验结构化内容。
- `GET /api/datasets/{id}/snapshots/{snapshot_id}/download`：下载 JSON 文档。

删除数据集时会删除其快照数据库记录，并清理应用 storage 中对应派生产物；原始数据文件仍不受影响。

## 差异与训练标签重建

快照比较使用同一数据集内的样本 ID 对齐，并分别报告 `added`、`removed`、`file`、`metadata`、`tags`、`split`、`annotations`。标注比较排除数据库 annotation id，只比较训练相关语义。摘要覆盖全部差异，筛选和分页只作用于明细。

训练标签重建生成规范化 JSON 中间产物：分类任务输出冻结的样本标签，检测/分割任务输出冻结的对象语义；路径、file hash、split、format、include-empty 和 class map 均来自快照。`label_sha256` 对规范化标签内容计算，重复读取或下载不得访问当前样本/标注表，也不得改变 dataset revision。

- `GET /api/datasets/{id}/snapshots/compare`：比较两个快照。
- `GET /api/datasets/{id}/snapshots/{snapshot_id}/training-labels`：读取规范化训练标签。
- `GET /api/datasets/{id}/snapshots/{snapshot_id}/training-labels/download`：下载标签 JSON。
