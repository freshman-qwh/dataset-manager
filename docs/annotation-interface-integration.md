# Dataset Manager 标注界面集成方案

本文档基于对 labelme 与 CVAT 仓库核心标注界面代码的阅读，目标是在当前 Dataset Manager MVP 中引入“最重要、最主要”的打标签界面：图片样本的几何标注、类别选择、对象列表、保存与导出。

## 1. 结论

当前项目不适合直接嵌入完整 CVAT，也不适合照搬 labelme 的 PyQt 桌面界面。推荐实现一个本项目原生的 React + SVG 标注工作区：

- UI 与交互分层借鉴 CVAT：画布只负责渲染与指针交互，标注对象状态、保存、历史记录、样本切换由外层管理。
- 数据格式语义借鉴 labelme：每个样本有 `shapes`，每个 shape 有 `label`、`points`、`shape_type`、`group_id`、`flags`、`description`。
- MVP 先支持图片：矩形框、 polygon、多点/关键点、对象类别、对象列表、撤销/重做、缩放/平移、手动保存。
- 当前 `Tag` 可以先作为对象类别字典复用，后续再拆出独立的 `AnnotationLabel`。

## 2. 源码阅读摘要

### 2.1 labelme 的做法

labelme 的核心标注界面是一个 PyQt `Canvas`：

- `Canvas` 继承 `QWidget`，内部维护 `shapes`、`selected_shapes`、当前绘制中的 `_current`、hover 顶点/边、缩放、平移、编辑/创建模式等状态。参考：`labelme/widgets/canvas.py` 的 `Canvas` 定义与信号。
- 交互入口集中在 `mouseMoveEvent`、`mousePressEvent`、`mouseReleaseEvent`，先把 widget 坐标转换成图片坐标，再根据当前模式分发到绘制、编辑、平移等逻辑。
- 新建形状逻辑是状态机：第一次点击创建 `Shape`，后续点击扩展点集；矩形、圆、线段在第二点时完成；polygon 点回到首点或触发完成时 finalize。
- 渲染顺序清晰：图片层、十字线、已提交形状、当前绘制形状、拖拽副本、预览覆盖层。
- `Shape` 是轻量模型，支持 `polygon`、`rectangle`、`oriented_rectangle`、`point`、`line`、`circle`、`linestrip`、`points`、`mask`，保存 label、点集、point labels、group、flags、description、mask 等。
- `LabelFile` 读写 JSON，顶层包含 `version`、`flags`、`shapes`、`imagePath`、`imageData`、`imageHeight`、`imageWidth`。

labelme 对本项目最有价值的部分：

- 单样本标注的数据结构简单，适合本地 SQLite 与 manifest 导出。
- 坐标始终以原始图片坐标保存，画布缩放只影响显示。
- 状态机足够轻，可以用于 MVP。

不建议照搬的部分：

- PyQt 事件系统不能直接用于 React/Vite。
- labelme 是文件级 JSON 工作流，本项目已经有 SQLite 元数据与 REST API，应避免写旁路 JSON 作为唯一真源。
- mask、AI 辅助、旋转矩形等可后置。

### 2.2 CVAT 的做法

CVAT 的标注界面是 Web 分层架构：

- `cvat-canvas` 暴露统一 `Canvas` API：`setup(frameData, objectStates)`、`draw(drawData)`、`edit(editData)`、`activate(clientID)`、`focus()`、`fit()`、`cancel()`、`configure()`。
- `CanvasModel` 控制模式与状态，定义 `IDLE`、`DRAW`、`EDIT`、`DRAG`、`RESIZE`、`INTERACT` 等模式，并在 busy 状态阻止互斥操作。
- `DrawHandler` 基于 SVG.js 处理具体绘制，按 shape 类型校验约束，比如 rectangle 需要最小宽高、polygon 至少 3 个点、polyline 至少 2 个点。
- `cvat-ui` 的 canvas wrapper 把底层自定义事件转换为业务动作：`canvas.drawn` 创建对象，`canvas.dragshape`/`canvas.resizeshape` 更新对象，`canvas.edited` 更新点集。
- `ObjectState` 是业务对象状态模型，包含 `clientID`、`shapeType`、`points`、`label`、`attributes`、`hidden`、`lock`、`updated` 等字段，并通过 update flags 追踪脏字段。
- `annotations-saver` 将 created / updated / deleted 拆开提交，适合多人和服务端场景。本项目 MVP 可以简化成单样本全量替换或批量 upsert。

CVAT 对本项目最有价值的部分：

- 画布 API 与业务状态分离。
- 明确的模式互斥，避免“绘制中又切样本/缩放/编辑”的状态错误。
- 对象列表是标注效率的关键界面，不只是画布。
- 所有画布事件最终变成对象状态变更，再由外层保存。

不建议照搬的部分：

- CVAT 依赖完整任务、job、frame、track、server saver、redux 大状态机，复杂度远超 MVP。
- 当前项目没有视频帧任务、多人协作、审查队列、云端任务分发，不应引入 CVAT 全量模型。

## 3. 本项目应实现的标注工作区

### 3.1 入口

在 Dataset Detail 页的样本卡片和详情面板中增加“标注”入口：

- 样本卡片双击或按钮进入 `/datasets/:datasetId/annotate?sample=:sampleId`。
- 详情侧栏增加 `Edit annotations` 按钮。
- 仅对 `file_type === "image"` 的样本启用；视频、表格先显示不可用提示。

推荐路由：

```text
frontend/src/pages/AnnotationPage.tsx
/datasets/:datasetId/annotate
```

### 3.2 首屏布局

采用 CVAT 式工作区，但保持本项目白色、简洁风格：

- 顶栏：返回数据集、样本名、上一个/下一个、保存状态、保存按钮。
- 左侧窄工具栏：选择、矩形、polygon、点、平移、撤销、重做、删除。
- 中央画布：图片 + SVG overlay。
- 右侧面板：对象列表、当前对象属性、类别选择、备注。
- 底部状态条：坐标、缩放比例、绘制提示、未保存状态。

### 3.3 MVP 功能清单

必须实现：

- 图片加载：使用现有 `GET /api/samples/{id}/file`。
- 标注读取：`GET /api/samples/{id}/annotations`。
- 标注保存：`PUT /api/samples/{id}/annotations`，元数据写 SQLite，不写回原始图片。
- 工具：选择、矩形、polygon、点。
- 编辑：移动对象、移动顶点、删除对象、改类别、改备注。
- 对象列表：按 z-order 显示，点击定位，高亮当前对象。
- 坐标：保存原始图片像素坐标，不保存屏幕坐标。
- 历史：前端内存撤销/重做栈。
- 状态：样本有标注后把 `review_status` 从 `unlabeled` 更新为 `in_review` 或 `approved` 由用户控制。
- 导出：manifest 增加 `annotations` 字段，并提供 labelme JSON 导出模板。

后续实现：

- brush / mask。
- skeleton。
- 自动保存。
- 标注质量检查。
- 快捷键可配置。
- 视频帧/track。
- COCO、YOLO、Pascal VOC 导出。

## 4. 后端实现方式

### 4.1 数据模型

MVP 可以新建 `Annotation` 表，复用当前 `Tag` 作为类别：

```python
# backend/app/models/annotation.py
from datetime import datetime
from sqlmodel import Field, SQLModel
from app.models.dataset import utc_now


class Annotation(SQLModel, table=True):
    __tablename__ = "annotations"

    id: int | None = Field(default=None, primary_key=True)
    sample_id: int = Field(foreign_key="samples.id", index=True)
    dataset_id: int = Field(foreign_key="datasets.id", index=True)
    tag_id: int | None = Field(default=None, foreign_key="tags.id", index=True)
    label: str = Field(index=True, max_length=120)
    shape_type: str = Field(index=True, max_length=40)
    points_json: str
    flags_json: str | None = Field(default=None)
    attributes_json: str | None = Field(default=None)
    group_id: int | None = Field(default=None, index=True)
    z_order: int = Field(default=0)
    locked: bool = Field(default=False)
    hidden: bool = Field(default=False)
    source: str = Field(default="manual", max_length=40)
    notes: str | None = Field(default=None, max_length=2000)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
```

字段说明：

- `sample_id`：单个样本的标注对象。
- `dataset_id`：便于按数据集统计与导出。
- `tag_id` + `label`：`tag_id` 关联当前标签字典，`label` 冗余保存名称，避免标签重命名后历史导出丢失语义。
- `shape_type`：`rectangle`、`polygon`、`point`、`points`。
- `points_json`：原图坐标数组，例如 rectangle 为 `[xtl, ytl, xbr, ybr]`，polygon 为 `[x1, y1, x2, y2, ...]`。
- `attributes_json`：对象级属性，后续支持 occluded、truncated、difficult 等。
- `hidden`、`locked`、`z_order`：对象列表和画布交互需要。

在 `backend/app/core/database.py` 中导入模型后 `SQLModel.metadata.create_all(engine)` 会创建新表。若后续给 `annotations` 增列，再按现有 `_ensure_columns` 风格补轻量回填。

### 4.2 Schemas

```python
# backend/app/schemas/annotation.py
from datetime import datetime
from pydantic import BaseModel, Field


class AnnotationBase(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    tag_id: int | None = None
    shape_type: str = Field(pattern="^(rectangle|polygon|point|points)$")
    points: list[float] = Field(min_length=2)
    flags: dict[str, bool] = Field(default_factory=dict)
    attributes: dict[str, object] = Field(default_factory=dict)
    group_id: int | None = None
    z_order: int = 0
    locked: bool = False
    hidden: bool = False
    source: str = "manual"
    notes: str | None = None


class AnnotationCreate(AnnotationBase):
    pass


class AnnotationRead(AnnotationBase):
    id: int
    sample_id: int
    dataset_id: int
    created_at: datetime
    updated_at: datetime


class AnnotationReplaceRequest(BaseModel):
    annotations: list[AnnotationCreate] = Field(default_factory=list)
    review_status: str | None = None
```

校验规则应放在 service：

- rectangle 必须 4 个数字，`xbr > xtl`，`ybr > ytl`。
- polygon 至少 6 个数字。
- point 必须 2 个数字。
- 坐标必须在图片范围内，允许保存时 clamp 或返回 400。建议 MVP 返回 400，避免静默改用户标注。
- sample 必须属于 dataset，且 `file_type === "image"`。

### 4.3 API

新增 REST 端点：

```text
GET    /api/samples/{sample_id}/annotations
PUT    /api/samples/{sample_id}/annotations
POST   /api/samples/{sample_id}/annotations/export-labelme
GET    /api/datasets/{dataset_id}/annotation-stats
```

MVP 的 `PUT` 推荐“单样本全量替换”：

- 前端编辑的是当前样本的完整对象列表。
- 保存时后端删除该 sample 的旧 annotation 记录，再插入新列表。
- 这是 metadata-only 删除，不触碰原始图片，符合数据安全规则。
- 如果担心并发，后续加 `annotations_version` 或 `updated_at` 乐观锁。

Service 结构：

```text
backend/app/
├── api/annotations.py
├── models/annotation.py
├── schemas/annotation.py
└── services/annotation_service.py
```

### 4.4 Service 逻辑

核心函数：

```python
def list_sample_annotations(session: Session, sample_id: int) -> list[AnnotationRead]:
    sample = sample_service.get_sample_or_404(session, sample_id)
    statement = select(Annotation).where(Annotation.sample_id == sample.id).order_by(Annotation.z_order)
    return [to_annotation_read(item) for item in session.exec(statement).all()]


def replace_sample_annotations(
    session: Session,
    sample_id: int,
    payload: AnnotationReplaceRequest,
) -> list[AnnotationRead]:
    sample = sample_service.get_sample_or_404(session, sample_id)
    if sample.file_type != "image":
        raise HTTPException(status_code=400, detail="Only image samples can be annotated.")

    image_size = read_image_size(sample.absolute_path)
    for item in payload.annotations:
        validate_annotation_points(item, image_size)

    old_items = session.exec(select(Annotation).where(Annotation.sample_id == sample_id)).all()
    for item in old_items:
        session.delete(item)

    created = []
    for index, item in enumerate(payload.annotations):
        tag = get_or_create_tag_if_needed(session, sample.dataset_id, item)
        annotation = Annotation(
            sample_id=sample.id,
            dataset_id=sample.dataset_id,
            tag_id=tag.id if tag else item.tag_id,
            label=item.label,
            shape_type=item.shape_type,
            points_json=json.dumps(item.points),
            flags_json=json.dumps(item.flags),
            attributes_json=json.dumps(item.attributes),
            group_id=item.group_id,
            z_order=item.z_order if item.z_order is not None else index,
            locked=item.locked,
            hidden=item.hidden,
            source=item.source,
            notes=item.notes,
        )
        session.add(annotation)
        created.append(annotation)

    if payload.review_status:
        sample.review_status = sample_service._validate_review_status(payload.review_status)
    elif created and sample.review_status == "unlabeled":
        sample.review_status = "in_review"
    sample.updated_at = utc_now()
    session.add(sample)
    session.commit()
    return [to_annotation_read(item) for item in created]
```

注意：

- 不移动、不删除、不覆盖图片。
- 全量替换只删除数据库 annotation 行，不删除样本记录。
- `read_image_size` 用 Pillow，只读取尺寸。
- label 不存在时可以复用 `sample_service._get_or_create_tag` 的思路，但建议迁到 `tag_service` 公开函数，避免调用私有函数。

### 4.5 导出格式

labelme JSON 导出：

```json
{
  "version": "dataset-manager",
  "flags": {},
  "shapes": [
    {
      "label": "scratch",
      "points": [[12.0, 20.0], [80.0, 90.0]],
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

Manifest 增加：

```json
{
  "id": 1,
  "relative_path": "a/b.jpg",
  "tags": ["scratch"],
  "annotations": [
    {
      "label": "scratch",
      "shape_type": "rectangle",
      "points": [12, 20, 80, 90],
      "attributes": {}
    }
  ]
}
```

## 5. 前端实现方式

### 5.1 文件结构

```text
frontend/src/
├── pages/
│   └── AnnotationPage.tsx
├── components/annotation/
│   ├── AnnotationWorkspace.tsx
│   ├── AnnotationCanvas.tsx
│   ├── AnnotationToolbar.tsx
│   ├── AnnotationObjectList.tsx
│   ├── AnnotationPropertiesPanel.tsx
│   └── useAnnotationHistory.ts
├── api/
│   └── client.ts
└── types/
    └── dataset.ts
```

### 5.2 TypeScript 类型

```ts
export type AnnotationShapeType = "rectangle" | "polygon" | "point" | "points";

export interface AnnotationObject {
  id?: number;
  sample_id?: number;
  dataset_id?: number;
  client_id: string;
  label: string;
  tag_id: number | null;
  shape_type: AnnotationShapeType;
  points: number[];
  flags: Record<string, boolean>;
  attributes: Record<string, unknown>;
  group_id: number | null;
  z_order: number;
  locked: boolean;
  hidden: boolean;
  source: "manual" | "file" | "auto" | string;
  notes: string | null;
}

export interface AnnotationReplaceRequest {
  annotations: Omit<AnnotationObject, "client_id">[];
  review_status?: string | null;
}
```

### 5.3 画布状态

`AnnotationCanvas` 不直接保存到后端，它只接收和抛出对象状态：

```ts
interface AnnotationCanvasProps {
  imageUrl: string;
  objects: AnnotationObject[];
  activeObjectId: string | null;
  tool: "select" | "pan" | "rectangle" | "polygon" | "point";
  zoom: number;
  onObjectsChange: (objects: AnnotationObject[]) => void;
  onActiveObjectChange: (clientId: string | null) => void;
}
```

内部状态：

- `imageNaturalSize`：图片原始宽高。
- `viewport`：当前可视区域尺寸。
- `transform`：`scale`、`translateX`、`translateY`。
- `draft`：当前绘制中的临时 shape。
- `hover`：hover 对象、顶点。
- `dragState`：拖拽对象、顶点或画布。

坐标转换：

```ts
function screenToImage(point: Point, transform: CanvasTransform): Point {
  return {
    x: (point.x - transform.translateX) / transform.scale,
    y: (point.y - transform.translateY) / transform.scale
  };
}

function imageToScreen(point: Point, transform: CanvasTransform): Point {
  return {
    x: point.x * transform.scale + transform.translateX,
    y: point.y * transform.scale + transform.translateY
  };
}
```

保存时永远使用 image 坐标。

### 5.4 绘制逻辑

矩形：

1. `pointerdown` 记录起点。
2. `pointermove` 更新 draft 的 `[x1, y1, x2, y2]`。
3. `pointerup` 如果宽高超过阈值，创建对象；否则丢弃。

Polygon：

1. 第一次点击创建 draft points。
2. 每次点击追加点。
3. 点击首点附近或双击完成。
4. Escape 取消，Backspace 删除上一点。
5. 至少 3 个点才允许提交。

点：

1. 点击即创建 `[x, y]`。

选择/编辑：

- 点击对象设为 active。
- 点击顶点进入顶点拖拽。
- 点击对象内部进入整体拖拽。
- Delete 删除 active 对象。
- 右侧列表改 label、hidden、locked、notes。

### 5.5 历史记录

实现 `useAnnotationHistory`：

```ts
function useAnnotationHistory(initial: AnnotationObject[]) {
  const [past, setPast] = useState<AnnotationObject[][]>([]);
  const [present, setPresent] = useState(initial);
  const [future, setFuture] = useState<AnnotationObject[][]>([]);

  function commit(next: AnnotationObject[]) {
    setPast((items) => [...items.slice(-49), present]);
    setPresent(next);
    setFuture([]);
  }

  function undo() {
    const previous = past[past.length - 1];
    if (!previous) return;
    setPast((items) => items.slice(0, -1));
    setFuture((items) => [present, ...items]);
    setPresent(previous);
  }

  function redo() {
    const next = future[0];
    if (!next) return;
    setPast((items) => [...items, present]);
    setFuture((items) => items.slice(1));
    setPresent(next);
  }

  return { objects: present, commit, undo, redo };
}
```

### 5.6 API client

在 `frontend/src/api/client.ts` 增加：

```ts
export async function listSampleAnnotations(sampleId: number): Promise<AnnotationObject[]> {
  const { data } = await client.get<AnnotationObject[]>(`/samples/${sampleId}/annotations`);
  return data.map((item) => ({ ...item, client_id: `server-${item.id}` }));
}

export async function replaceSampleAnnotations(
  sampleId: number,
  payload: AnnotationReplaceRequest
): Promise<AnnotationObject[]> {
  const { data } = await client.put<AnnotationObject[]>(`/samples/${sampleId}/annotations`, payload);
  return data.map((item) => ({ ...item, client_id: `server-${item.id}` }));
}
```

### 5.7 AnnotationPage 数据流

```text
route sample_id
  -> getSample(sample_id)
  -> listTags(dataset_id)
  -> listSampleAnnotations(sample_id)
  -> render AnnotationWorkspace
  -> user edits local objects
  -> save button PUT /annotations
  -> update dirty=false, refresh sample review_status
```

切换样本前：

- 如果 dirty，弹出确认：保存 / 放弃 / 取消切换。
- 保存成功后才能跳转，避免丢失对象状态。

### 5.8 与当前 SampleGrid / DetailPanel 的结合

需要改动：

- `frontend/src/App.tsx` 增加 annotate route。
- `frontend/src/pages/DatasetDetailPage.tsx` 增加进入标注页的回调。
- `frontend/src/components/SampleGrid.tsx` 在图片样本卡片增加图标按钮。
- `frontend/src/components/SampleDetailPanel.tsx` 增加“标注”按钮，并显示 annotation count。
- `backend/app/services/stats_service.py` 增加 `annotated_samples`、`annotation_count`、`by_annotation_label`。

## 6. 代码实现优先级

### Phase 1：最小可用标注

后端：

1. 新建 annotation model/schema/service/api。
2. 注册 router。
3. 添加 list/replace 单元测试。
4. manifest 导出带 annotations。

前端：

1. 新建 AnnotationPage。
2. 图片 + SVG overlay。
3. rectangle / polygon / point 绘制。
4. 右侧对象列表与 label 选择。
5. 保存、dirty 提示、撤销/重做。

验收：

- 扫描一个图片数据集。
- 打开一张图片，画矩形和 polygon。
- 切换标签、保存、刷新页面后标注仍存在。
- 导出 manifest 包含标注。
- 原始图片未被修改。

### Phase 2：效率功能

- 上一张/下一张。
- 快捷键：`V` 选择，`R` 矩形，`P` polygon，`H` 平移，`Ctrl+S` 保存，`Delete` 删除，`Esc` 取消。
- 对象 hidden/locked。
- 自动 fit image。
- 标注统计。

### Phase 3：格式兼容

- labelme JSON 导入/导出。
- COCO detection/segmentation 导出。
- YOLO bbox 导出。
- Pascal VOC bbox 导出。

## 7. 实现细节与边界

### 7.1 坐标规范

- 数据库存原始图片像素坐标。
- 前端渲染时按 `transform.scale` 映射。
- 矩形统一存 `[xtl, ytl, xbr, ybr]`。
- polygon / points 统一存扁平数组 `[x1, y1, x2, y2]`。
- 导出 labelme 时转换成二维数组 `[[x, y], ...]`。

### 7.2 标签与对象标签的关系

短期复用 `Tag`：

- Dataset 级标签列表就是可选类别。
- 创建新对象 label 时，如果标签不存在，后端创建 `Tag`。
- `Annotation.label` 冗余保存当前名称。

长期拆分：

- `Tag` 保持样本级组织标签。
- `AnnotationLabel` 表示任务类别，支持属性 schema、颜色、快捷键。

### 7.3 保存策略

MVP 使用手动保存：

- 前端编辑对象后 `dirty=true`。
- 保存按钮发送当前样本完整 annotations。
- 后端在一个事务内替换。

后续自动保存：

- 2 秒 debounce。
- 保存失败保留 dirty。
- 切换样本前强制处理 dirty 状态。

### 7.4 数据安全

必须遵守：

- 标注保存只写 SQLite。
- 不写回图片文件。
- 不在原始数据目录生成旁路 JSON，除非用户显式导出。
- 删除 annotation 只删除数据库记录，不删除 raw file。

### 7.5 为什么不用 canvas 2D

MVP 推荐 SVG overlay：

- 形状和顶点天然是 DOM 元素，hover、选中、拖拽更直观。
- React 状态与 SVG 属性映射简单。
- 矩形、polygon、点足够流畅。

后续 mask/brush 再引入 Canvas bitmap layer。

## 8. 参考源码

labelme：

- Canvas 状态、模式、事件入口、渲染层：[labelme/widgets/canvas.py](https://github.com/wkentaro/labelme/blob/e6b9ca6ccf6d8a039bd1c698ce1bb149033ab810/labelme/widgets/canvas.py#L63)
- Shape 数据与绘制：[labelme/_shape.py](https://github.com/wkentaro/labelme/blob/e6b9ca6ccf6d8a039bd1c698ce1bb149033ab810/labelme/_shape.py#L46)
- labelme JSON 文件结构：[labelme/_label_file.py](https://github.com/wkentaro/labelme/blob/e6b9ca6ccf6d8a039bd1c698ce1bb149033ab810/labelme/_label_file.py#L144)

CVAT：

- Canvas 对外 API：[cvat-canvas/src/typescript/canvas.ts](https://github.com/cvat-ai/cvat/blob/f03d0396814af925f4728fc090f633abe0eaae34/cvat-canvas/src/typescript/canvas.ts#L18)
- Canvas 模式与 draw/edit 校验：[cvat-canvas/src/typescript/canvasModel.ts](https://github.com/cvat-ai/cvat/blob/f03d0396814af925f4728fc090f633abe0eaae34/cvat-canvas/src/typescript/canvasModel.ts#L196)
- SVG 绘制处理器：[cvat-canvas/src/typescript/drawHandler.ts](https://github.com/cvat-ai/cvat/blob/f03d0396814af925f4728fc090f633abe0eaae34/cvat-canvas/src/typescript/drawHandler.ts#L49)
- React canvas wrapper 事件桥接：[cvat-ui/src/components/annotation-page/canvas/views/canvas2d/canvas-wrapper.tsx](https://github.com/cvat-ai/cvat/blob/f03d0396814af925f4728fc090f633abe0eaae34/cvat-ui/src/components/annotation-page/canvas/views/canvas2d/canvas-wrapper.tsx#L428)
- ObjectState 对象模型：[cvat-core/src/object-state.ts](https://github.com/cvat-ai/cvat/blob/f03d0396814af925f4728fc090f633abe0eaae34/cvat-core/src/object-state.ts#L70)
- annotations saver created/updated/deleted 拆分：[cvat-core/src/annotations-saver.ts](https://github.com/cvat-ai/cvat/blob/f03d0396814af925f4728fc090f633abe0eaae34/cvat-core/src/annotations-saver.ts#L224)

