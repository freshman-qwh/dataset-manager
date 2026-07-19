# 标注格式兼容与导出契约设计

本文档定义 `v0.4.0 Phase 2` 批次 C 的标注格式兼容、导入导出、预检与代码结构契约。批次 C 已于 2026-07-19 完成实现，后续修改应继续遵守本文的格式与数据安全边界。

参考入口：

- 项目标注界面设计：`docs/annotation-interface-integration.md`
- 当前 TODO 批次 C：`TODO.md`
- Ultralytics YOLO detection/segmentation 数据集说明：`https://docs.ultralytics.com/datasets/detect/`、`https://docs.ultralytics.com/datasets/segment/`
- COCO 官方格式入口：`https://cocodataset.org/#format-data`

## 1. 核心结论

### 1.1 YOLO bbox 为什么原先写成不支持 polygon

YOLO detection 的常用 `.txt` 行格式是：

```text
class_id x_center y_center width height
```

其中 `x_center/y_center/width/height` 都是相对图片宽高归一化后的 bbox，而不是 polygon 顶点。因此如果目标导出格式明确是 `YOLO bbox` 或 `YOLO detection`，polygon 不能原样保留，只能转换成包围框。

转换规则：

```text
x_min = min(polygon.x)
y_min = min(polygon.y)
x_max = max(polygon.x)
y_max = max(polygon.y)

x_center = ((x_min + x_max) / 2) / image_width
y_center = ((y_min + y_max) / 2) / image_height
width = (x_max - x_min) / image_width
height = (y_max - y_min) / image_height
```

这是一种有损转换：训练目标检测模型时可接受，但 polygon 的真实轮廓会丢失。导出预检必须把这类转换标记为 warning，而不是静默发生。

### 1.2 polygon 是否等于分割

在本项目当前语义下，polygon 是一种矢量轮廓标注，可以用于实例分割导出。它不等于 brush/mask，但可以作为 segmentation polygon。

- polygon segmentation：顶点围成对象轮廓，适合 COCO segmentation、YOLO segmentation。
- brush/mask segmentation：像素级栅格遮罩，通常需要画笔大小、橡皮擦、mask 图层、RLE 或位图存储。

MVP 暂不做 brush/mask 不影响 polygon segmentation 导出。限制是：只能导出多边形轮廓，不能导出像素级自由涂抹遮罩。

### 1.3 批次 C 应拆成两类 YOLO 导出

后续实现不应只有一个模糊的 `yolo`：

- `yolo_detection`：输出 bbox，rectangle 直接导出，polygon 转外接 bbox 并 warning，point/points 默认不导出。
- `yolo_segmentation`：输出 polygon 顶点，polygon 直接导出，rectangle 可转 4 点矩形 polygon 并 warning，point/points 默认不导出。

这样可以避免“YOLO 是否支持 polygon”的歧义：YOLO detection 不保存 polygon；YOLO segmentation 支持 polygon。

## 2. 当前内部数据契约

当前后端 `Annotation` 记录的关键字段：

```text
sample_id
dataset_id
tag_id
label
shape_type: rectangle | polygon | point | points
points_json
flags_json
attributes_json
group_id
z_order
locked
hidden
source
notes
```

内部坐标统一存原始图片像素坐标，不存屏幕坐标，不做归一化存储。

### 2.1 shape 坐标规范

```text
rectangle:
  points = [xtl, ytl, xbr, ybr]
  约束：xbr > xtl, ybr > ytl

polygon:
  points = [x1, y1, x2, y2, ..., xn, yn]
  约束：n >= 3，数组长度为偶数

point:
  points = [x, y]

points:
  points = [x1, y1, x2, y2, ..., xn, yn]
  约束：n >= 1，数组长度为偶数
```

批次 C 的导入导出层不应改变数据库中的坐标表示。所有格式差异都放在 export/import service 做转换。

### 2.2 后续需要补强的内部校验

批次 C 可以先在导出预检中做完整检查；批次 D 再把相同校验沉到保存与质量检查中。

必须检查：

- 坐标为有限数字。
- 坐标不为负。
- 坐标不超过图片宽高。
- rectangle 宽高为正。
- polygon 至少 3 个点，且面积大于 0。
- label 非空，且能映射到导出类别。
- image width/height 可读取。

导出层不得静默 clamp 越界坐标。发现越界时应给出 error，由用户回到标注页修正。

## 3. 格式兼容矩阵

| 格式 | rectangle | polygon | point | points | 备注 |
| --- | --- | --- | --- | --- | --- |
| labelme export | 支持 | 支持 | 支持 | 支持 | 与当前 `shape_type` 基本同构 |
| labelme import | 支持 | 支持 | 支持 | 支持 | 只写 SQLite，不写回图片目录 |
| COCO detection | 支持 bbox | 转 bbox，warning | 不支持 | 不支持 | polygon 到 bbox 是有损转换 |
| COCO segmentation | 转 4 点 polygon，warning | 支持 | 不支持 | 不支持 | MVP 只支持 polygon，不支持 RLE mask |
| YOLO detection | 支持 bbox | 转 bbox，warning | 不支持 | 不支持 | 输出归一化 xywh |
| YOLO segmentation | 转 4 点 polygon，warning | 支持 | 不支持 | 不支持 | 输出归一化 polygon 顶点 |
| Pascal VOC | 支持 bbox | 转 bbox，warning | 不支持 | 不支持 | XML bbox 为像素坐标 |

默认策略：

- 不兼容对象不导出，并在 precheck/export report 中列为 error 或 warning。
- 有损转换必须写入 export report。
- point/points 暂不自动扩成小框，因为缺少半径/尺寸契约，容易制造假 bbox。

## 4. 类别映射契约

导出时应从 annotation 对象标签而不是 sample tags 推导类别，避免样本级标签污染对象级训练标签。

类别来源优先级：

1. `Annotation.tag_id` 对应的 `Tag.name`。
2. `Annotation.label`。

默认排序：

```text
按类别名称升序排序，生成稳定 class_map。
```

ID 规则：

```text
COCO category_id: 从 1 开始
YOLO class_id: 从 0 开始
VOC name: 使用类别名称字符串
labelme label: 使用类别名称字符串
```

每次导出都应附带 `export_report.json` 或 response metadata：

```json
{
  "class_map": [
    {"name": "666", "coco_id": 1, "yolo_id": 0},
    {"name": "777", "coco_id": 2, "yolo_id": 1}
  ]
}
```

后续可在 UI 增加自定义类别顺序，但批次 C 先用稳定默认排序。

## 5. 几何转换契约

建议新增纯函数模块承载格式无关转换，避免各导出 service 重复实现。

```text
backend/app/services/annotation_geometry.py
```

核心函数：

```python
def pair_points(points: list[float]) -> list[tuple[float, float]]:
    ...

def rectangle_to_bbox(points: list[float]) -> BBox:
    ...

def polygon_to_bbox(points: list[float]) -> BBox:
    ...

def rectangle_to_polygon(points: list[float]) -> list[float]:
    ...

def polygon_area(points: list[float]) -> float:
    ...

def bbox_area(bbox: BBox) -> float:
    ...

def bbox_to_coco_xywh(bbox: BBox) -> list[float]:
    ...

def bbox_to_yolo_xywh(bbox: BBox, width: int, height: int) -> list[float]:
    ...

def polygon_to_yolo_segment(points: list[float], width: int, height: int) -> list[float]:
    ...
```

推荐 `BBox` 语义：

```python
@dataclass(frozen=True)
class BBox:
    x_min: float
    y_min: float
    x_max: float
    y_max: float
```

不要在几何函数中读取数据库或抛 HTTPException。它们应只做数学转换，由上层 precheck/export service 决定错误表现。

## 6. 导出契约

### 6.1 labelme

单样本 JSON：

```json
{
  "version": "dataset-manager",
  "flags": {},
  "shapes": [
    {
      "label": "defect",
      "points": [[10.0, 20.0], [80.0, 120.0]],
      "group_id": null,
      "description": "",
      "shape_type": "rectangle",
      "flags": {}
    }
  ],
  "imagePath": "relative/path/image.jpg",
  "imageData": null,
  "imageHeight": 1024,
  "imageWidth": 1280
}
```

目录/数据集导出建议打包为 zip：

```text
annotations/
  relative/path/image_001.json
  relative/path/image_002.json
export_report.json
```

`imageData` 默认 `null`，避免把大图二进制塞进 JSON。

### 6.2 COCO detection

输出单个 JSON：

```json
{
  "info": {"description": "dataset-name", "version": "dataset-manager"},
  "licenses": [],
  "images": [
    {"id": 1, "file_name": "a/b.jpg", "width": 1280, "height": 1024}
  ],
  "annotations": [
    {
      "id": 1,
      "image_id": 1,
      "category_id": 1,
      "bbox": [10.0, 20.0, 70.0, 100.0],
      "area": 7000.0,
      "segmentation": [],
      "iscrowd": 0
    }
  ],
  "categories": [
    {"id": 1, "name": "defect", "supercategory": "object"}
  ]
}
```

转换规则：

- rectangle：`[xtl, ytl, xbr, ybr]` -> `[x, y, w, h]`。
- polygon：用 min/max 外接框导出 bbox，`segmentation` 留空或可选保留。为避免 detection/segmentation 混用，MVP detection 建议 `segmentation: []`。
- area：bbox 面积。
- point/points：跳过并报不兼容。

### 6.3 COCO segmentation

输出单个 JSON，annotation 包含 polygon segmentation：

```json
{
  "id": 1,
  "image_id": 1,
  "category_id": 1,
  "bbox": [10.0, 20.0, 70.0, 100.0],
  "area": 6500.0,
  "segmentation": [[10.0, 20.0, 80.0, 20.0, 75.0, 120.0]],
  "iscrowd": 0
}
```

转换规则：

- polygon：`segmentation = [points]`，bbox 用 polygon 外接框，area 用 polygon 面积。
- rectangle：转为四点 polygon，area 用 bbox 面积，并给 warning。
- point/points：跳过并报不兼容。
- `iscrowd` MVP 固定为 `0`，不支持 RLE crowd mask。

### 6.4 YOLO detection

每张图一个 `.txt`，每行一个对象：

```text
0 0.351562 0.341797 0.054688 0.097656
```

包结构：

```text
labels/
  train/
    relative/path/image_001.txt
  val/
    relative/path/image_002.txt
data.yaml
classes.txt
export_report.json
```

`data.yaml`：

```yaml
path: .
train: images/train
val: images/val
test:
names:
  0: defect
  1: scratch
```

数据安全约束：

- 默认只导出 label 文件和配置，不复制原始图片，不在原始目录写 `.txt`。
- 如果后续支持复制图片到导出包或导出目录，必须由用户显式选择，并且目标必须是导出目录，不是 raw dataset 目录。

转换规则：

- rectangle：直接转归一化 xywh。
- polygon：先外接 bbox，再归一化 xywh，写 warning。
- point/points：跳过并报不兼容。
- 空标注图片：允许没有 `.txt`，但 report 中统计。

### 6.5 YOLO segmentation

每张图一个 `.txt`，每行一个对象：

```text
0 0.100000 0.200000 0.300000 0.200000 0.250000 0.400000
```

转换规则：

- polygon：顶点坐标分别除以 image width/height 后输出。
- rectangle：转为四点 polygon，写 warning。
- point/points：跳过并报不兼容。
- 每个 segment 至少 3 个点。

包结构与 `yolo_detection` 相同，但 task metadata 标记为 `segment`：

```yaml
task: segment
names:
  0: defect
```

### 6.6 Pascal VOC

每张图一个 XML：

```xml
<annotation>
  <folder>dataset-name</folder>
  <filename>image_001.jpg</filename>
  <path>relative/path/image_001.jpg</path>
  <size>
    <width>1280</width>
    <height>1024</height>
    <depth>3</depth>
  </size>
  <object>
    <name>defect</name>
    <pose>Unspecified</pose>
    <truncated>0</truncated>
    <difficult>0</difficult>
    <bndbox>
      <xmin>10</xmin>
      <ymin>20</ymin>
      <xmax>80</xmax>
      <ymax>120</ymax>
    </bndbox>
  </object>
</annotation>
```

转换规则：

- rectangle：直接导出。
- polygon：转外接 bbox，写 warning。
- point/points：跳过并报不兼容。
- `difficult/truncated` 后续从 `attributes` 读取，当前默认 `0`。

## 7. 导入契约

批次 C 只规划 labelme JSON 导入。

### 7.1 输入范围

支持：

- 单个 labelme JSON 文件导入到指定 sample。
- 目录导入：扫描目录下 `.json`，按 `imagePath`、相对路径、文件名匹配 dataset samples。

不支持：

- 从 labelme JSON 中解码 `imageData` 创建新 raw file。
- 写回 labelme JSON 到原始图片目录。
- mask shape 导入。

### 7.2 写入策略

请求参数需要明确 merge 策略：

```text
replace_sample_annotations: 默认，匹配样本后替换该样本全部 annotations
append_annotations: 追加导入对象，保留已有对象
dry_run: 只预检不写入
```

推荐第一版 API：

```text
POST /api/datasets/{dataset_id}/annotations/import-labelme
```

请求体：

```json
{
  "path": "D:/datasets/kjb-pcb/labels",
  "mode": "directory",
  "strategy": "replace",
  "dry_run": true,
  "sync_sample_tags": true
}
```

响应体：

```json
{
  "matched_files": 120,
  "imported_samples": 118,
  "created_annotations": 530,
  "warnings": [],
  "errors": []
}
```

### 7.3 labelme shape 映射

```text
labelme rectangle -> rectangle
labelme polygon -> polygon
labelme point -> point
labelme points -> points
```

坐标统一转回当前内部扁平数组：

```text
[[x1, y1], [x2, y2]] -> [x1, y1, x2, y2]
```

未知 shape：

- `circle`、`line`、`linestrip`、`mask` 等第一版不导入。
- precheck 中列 warning 或 error，由用户决定是否继续。

## 8. 导出预检契约

建议新增统一 precheck，供 UI 在真正下载前展示问题。

API：

```text
POST /api/datasets/{dataset_id}/annotation-export-precheck
```

请求体：

```json
{
  "format": "yolo_detection",
  "sample_query": {
    "file_type": "image",
    "split": "train"
  },
  "include_empty": false
}
```

响应体：

```json
{
  "format": "yolo_detection",
  "sample_count": 4800,
  "annotated_sample_count": 120,
  "exportable_object_count": 450,
  "skipped_object_count": 12,
  "class_map": [{"name": "defect", "id": 0}],
  "issues": [
    {
      "severity": "warning",
      "code": "POLYGON_TO_BBOX",
      "sample_id": 17165,
      "annotation_id": 88,
      "message": "polygon 将以外接 bbox 导出到 YOLO detection。"
    }
  ],
  "blocked": false
}
```

严重级别：

- `error`：会导致导出失败或生成无效训练数据。
- `warning`：可以导出，但存在有损转换或样本跳过。
- `info`：统计性提示。

默认阻断条件：

- 没有图片样本。
- 没有可导出的对象。
- 类别映射为空。
- 坐标越界或非法。
- 目标格式没有任何兼容 shape。

默认 warning：

- polygon 转 bbox。
- rectangle 转 segmentation polygon。
- 空标注图片被跳过。
- 未设置 split，归入 `unassigned`。

## 9. 后端代码框架

建议将当前 `export_template_service.py` 保留为“模板预览”兼容接口，新建真实导入导出模块。

```text
backend/app/
├── api/
│   ├── annotations.py
│   └── annotation_exports.py
├── schemas/
│   ├── annotation.py
│   └── annotation_export.py
└── services/
    ├── annotation_service.py
    ├── annotation_geometry.py
    ├── annotation_export_service.py
    ├── annotation_import_service.py
    └── annotation_export_precheck_service.py
```

职责边界：

- `annotation_geometry.py`：纯几何函数，不读数据库，不依赖 FastAPI。
- `annotation_export_precheck_service.py`：查询样本/标注/图片尺寸，返回 issues。
- `annotation_export_service.py`：按格式组装 JSON、TXT、XML、ZIP。
- `annotation_import_service.py`：读取 labelme JSON，匹配样本，转换为内部 annotation payload。
- `annotation_exports.py`：薄路由，只做参数接收与 service 调用。
- `schemas/annotation_export.py`：请求、响应、issue、class map、export report 类型。

第一版 API 建议：

```text
POST /api/datasets/{dataset_id}/annotation-export-precheck
GET  /api/datasets/{dataset_id}/annotation-export?format=labelme|coco_detection|coco_segmentation|yolo_detection|yolo_segmentation|voc
POST /api/datasets/{dataset_id}/annotations/import-labelme
```

对于较大数据集，批次 F 再把导入导出改成后台任务；批次 C 可以同步生成，但需要控制响应大小并优先 zip streaming。

## 10. 前端工作流

保留现有 `ExportPreviewModal`，但批次 C 需要从“导出模板预览”升级为“真实标注导出向导”。

建议新增：

```text
frontend/src/components/AnnotationExportModal.tsx
frontend/src/components/AnnotationImportModal.tsx
frontend/src/types/annotationExport.ts
```

导出向导步骤：

1. 选择格式：labelme、COCO detection、COCO segmentation、YOLO detection、YOLO segmentation、Pascal VOC。
2. 选择样本范围：当前筛选、全数据集、指定 split。
3. 运行预检：展示 error/warning/info，尤其展示有损转换。
4. 用户确认后下载。

UI 文案必须明确：

- `YOLO detection`：导出 bbox；polygon 会转外接框。
- `YOLO segmentation`：导出 polygon 顶点；不需要 brush/mask。
- `COCO segmentation`：当前只支持 polygon，不支持 RLE mask。

导入向导步骤：

1. 选择 labelme JSON 文件或目录路径。
2. 选择匹配策略和写入策略。
3. dry run 预检。
4. 确认后写入 SQLite，并刷新统计/标签。

## 11. 实施顺序

推荐批次 C 拆成 5 个小 PR/提交：

1. 几何工具与预检框架
   - 新增 `annotation_geometry.py`
   - 新增 export precheck schema/service/API
   - 测试 rectangle/polygon bbox、面积、归一化

2. labelme import/export 补全
   - 补齐 labelme export dataset zip
   - 新增 labelme import dry-run 和 replace
   - 测试 rectangle/polygon/point/points 映射

3. COCO detection/segmentation
   - 实现 COCO JSON 真实导出
   - 明确 detection 与 segmentation mode
   - 测试 class map、image id、bbox、segmentation、area

4. YOLO detection/segmentation
   - 实现 labels zip、data.yaml、classes.txt、report
   - detection 支持 polygon -> bbox warning
   - segmentation 支持 polygon 顶点

5. Pascal VOC 与前端导出向导
   - 实现 VOC XML
   - 前端接入预检、下载和问题展示

## 12. 测试计划

后端单元测试：

- `test_annotation_geometry.py`
  - rectangle to bbox
  - polygon to bbox
  - polygon area
  - yolo normalized xywh
  - yolo normalized segment

- `test_annotation_export_precheck.py`
  - 空数据集 blocked
  - polygon to bbox warning
  - point incompatible error/warning
  - 越界坐标 error

- `test_annotation_export_service.py`
  - COCO detection JSON 字段完整
  - COCO segmentation polygon 输出
  - YOLO detection txt 行格式
  - YOLO segmentation txt 行格式
  - VOC XML 字段完整

- `test_annotation_import_labelme.py`
  - 单文件导入
  - 目录匹配
  - unknown shape 预检
  - replace/append 策略

前端验证：

- 导出向导格式切换文案正确。
- 预检错误阻断下载。
- warning 允许继续并展示转换说明。
- 下载文件名、扩展名和 MIME 类型正确。

人工验收数据集：

- 1 张 rectangle。
- 1 张 polygon。
- 1 张 rectangle + polygon 混合。
- 1 张 point/points。
- 1 张空标注。
- 1 张越界坐标样本，用于验证 blocked。

## 13. 暂不进入批次 C 的内容

- brush/mask 像素级标注工具。
- COCO RLE mask。
- skeleton/keypoints 训练格式。
- oriented bbox / rotated box。
- 自动修复越界坐标。
- 把原始图片复制或改写到数据目录。
- 后台任务化导出进度。

这些内容分别属于 MVP 外、批次 D 质量检查、或批次 F 工程化。
