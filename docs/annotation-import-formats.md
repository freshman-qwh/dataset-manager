# 通用标注导入：LabelMe、YOLO 与 COCO

## 产品目标

把已有 LabelMe 导入升级为一个一致的“导入标注”工作流。用户只需选择格式和本机来源，系统先只读预检，再把可确认的对象写入 SQLite；导入完成后直接进入现有 AnnotationPage 查看和继续编辑。整个过程不移动、重命名、覆盖或改写原始图片和来源标注文件，也不在原始目录生成 sidecar。

## 交互流程

1. 在数据集详情的“其他操作”中打开“导入标注”。
2. 选择 LabelMe JSON、YOLO detection、YOLO segmentation 或 COCO JSON。
3. 填写后端可读取的本机绝对路径。LabelMe 可选单文件或目录；YOLO 使用数据集目录；COCO 使用单个 JSON。
4. 选择替换或追加，并决定是否把对象类别追加为样本标签。LabelMe 单文件仍可指定样本 ID。
5. 执行只读预检。摘要显示检查文件、匹配样本、计划对象和跳过对象；错误与警告同时展示错误码、说明、来源文件和目标样本。
6. 确认后创建本地任务。关闭弹窗不会中断任务；任务中心提供进度、取消、重试和显式回滚。
7. 成功后在标注页打开任一样本。导入后的 rectangle / polygon 复用现有画布、对象列表、类别与保存流程。

任何路径、格式、范围、写入策略、样本 ID 或类别同步选项变化都会使旧预检失效。预检与任务创建均校验来源指纹和规范化写入计划指纹，来源内容或样本匹配改变时要求重新预检。

## 格式契约

### LabelMe

- 保持现有文件/目录、`imagePath`、可选样本 ID 和 rectangle / polygon / point / points 支持。
- 旧 `/annotations/import-labelme` 与 LabelMe 任务 API 保留兼容；新界面使用通用 API。

### YOLO

- 来源是目录；优先从 `data.yaml` 的 `names` 读取类别，无法读取时使用 `classes.txt`。
- 从 `labels/**/*.txt`（不存在 `labels/` 时为所选目录）读取标签；先按相对路径匹配，再以唯一文件名 stem 回退。歧义匹配不会猜测目标样本。
- detection 行为 `class cx cy width height`，归一化 bbox 转为像素 rectangle。
- segmentation 行为 `class x1 y1 x2 y2 ...`，归一化顶点转为像素 polygon。
- 坐标必须有限且位于 0..1，转换后必须在原图范围内。类别 ID 必须存在。
- pose、OBB 及与所选格式不一致的行返回 `UNSUPPORTED_YOLO_FORMAT`，不会静默导入。

### COCO

- 来源是单个 JSON，必须包含 `images`、`categories`、`annotations` 数组。
- `images[].file_name` 先按数据集相对路径匹配，再按唯一文件名匹配。
- `bbox [x,y,w,h]` 转为 rectangle；polygon segmentation 转为 polygon。多段 polygon 会拆为同组的多个 polygon，并给出 warning。
- RLE mask 暂不转为像素 mask；有 bbox 时给 warning 后使用 bbox，否则产生阻断该对象的 error。
- 缺失类别、重复 image id / file_name、缺失 image、重复样本匹配、非法几何和越界坐标均返回稳定的结构化诊断。

## 技术方案

- `AnnotationImportRequest` 以 `format` 统一 LabelMe、YOLO 和 COCO；`/api/datasets/{id}/annotations/import` 同时承担 dry-run 和旧库同步兼容写入。
- 三种解析器只负责“来源 → 规范化操作计划”。操作统一为目标 sample、来源文件和 `AnnotationCreate[]`，不直接写源文件。
- 来源指纹覆盖实际参与解析的配置和标注文件；计划指纹覆盖格式、目标 sample 与规范化对象。
- `annotation.import` 任务冻结格式、来源/计划指纹、文件数、样本数与对象数，按 25 个样本短事务写入。replace 与 append 共用恢复日志；append 重试从首次导入前快照重建，避免重复追加。
- `annotation.import.rollback` 使用应用存储中的 JSONL 恢复日志还原标注、标注进度、审核状态、样本标签和更新时间。导入过程中创建的类别/标签定义不自动删除。
- 保存仍通过 `replace_sample_annotations`，所以 AnnotationClass 创建、图片边界校验、SQLite 数据模型和 AnnotationPage 可视化均复用现有契约。

## 安全边界

- 读取：标注配置、标注文件、已登记样本元数据与原图尺寸。
- 写入：SQLite 标注、类别、可选样本标签、任务记录，以及应用存储中的回滚日志。
- 不写入：原图、来源 JSON/TXT/YAML、原始数据集目录、邻接 sidecar。
- 取消或失败可保留已提交短批次，但任务结果会明确记录进度；用户可重试或显式回滚。
