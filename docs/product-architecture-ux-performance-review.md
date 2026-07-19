# 产品、架构、体验与性能综合评审

评审日期：2026-07-19
评审范围：当前 `v0.4.0 Phase 2` 本地优先 MVP，包括数据集扫描、样本管理、标注、质量信息与训练格式导入导出链路。

## 1. 结论摘要

当前方向是正确的：本项目最有差异化价值的不是成为另一个大型在线标注平台，而是成为一个安全、轻量、可审计的本地研究数据集工作台。

现阶段不建议重写框架，也不建议立即引入微服务、Redis、Celery、PostgreSQL、向量数据库或桌面封装。React + FastAPI + SQLModel/SQLAlchemy + SQLite 的模块化单体足以支撑下一阶段。

下一阶段最值得投入的四项工作，按顺序为：

1. **标注质量工作台**：把空标注、越界、重复对象、类别异常、split 泄漏和审查状态集中成可定位、可修复的闭环。
2. **数据库查询下推与性能基线**：先把筛选、排序、分页、统计和重复检测从 Python 全量内存处理迁移到 SQL，再讨论换数据库。
3. **本地任务中心**：扫描、缩略图、导入、导出、备份改为有进度、可取消、可重试的本地任务，避免长请求占用 API 工作线程。
4. **数据集快照与可复现导出**：版本化的是 manifest、标签、标注、split、格式配置和文件 hash，不复制原始数据；能够比较两个快照并复现训练输入。

产品层面最有吸引力的后续能力是近重复/跨 split 泄漏分析和模型结果回流，但它们应建立在质量工作台、任务中心和查询性能完成之后。

## 2. 同类项目调研

### 2.1 CVAT

CVAT 的优势是完整的 project/task/job 层级、标注工作流、质量控制、共识标注、分析和备份。其官方文档把 Dataset Management、Annotation、QA & Analytics 分成清晰模块；轻量备份可以只保存任务元数据和标注，不复制原始媒体。

值得借鉴：

- 质量问题必须和“定位到具体样本/对象、修复、复核”结合，而不是只显示统计数字。
- 扫描、导入、导出、备份应是异步任务，有状态和结果报告。
- 轻量备份与本项目“原始文件留在磁盘、SQLite 存元数据”的边界高度一致。

不建议照搬：

- 当前不需要 project/task/job 多层组织、团队权限、共识标注和在线协作复杂度。
- 不应为了模仿 CVAT 提前引入分布式队列和微服务。

参考：[CVAT 文档总览](https://docs.cvat.ai/docs/)、[QA & Analytics](https://docs.cvat.ai/docs/qa-analytics/)、[轻量备份](https://docs.cvat.ai/docs/dataset_management/backup/)。

### 2.2 Label Studio

Label Studio 的 Data Manager 把任务浏览、筛选、排序、导入、导出和批量操作放在同一工作面；过滤结果也会影响后续标注顺序。它还提供模型后端与预测回流能力。

值得借鉴：

- 保存筛选视图，让“待审核”“某 split 的缺陷类”“导出候选集”成为可复用工作入口。
- 当前筛选结果应贯穿浏览、标注、批量操作和导出，作用域必须始终可见。
- 后续可支持“导入预测结果”，但先做静态预测导入和人工复核，不需要立即建设在线 ML Backend。

参考：[Label Studio Data Manager](https://labelstud.io/guide/manage_data)、[Label Studio 架构概览](https://labelstud.io/guide/get_started)、[ML 集成](https://labelstud.io/guide/ml)。

### 2.3 FiftyOne

FiftyOne 的核心优势是数据集视图、相似度、精确/近重复、跨 split 泄漏、唯一性、标签错误发现，以及模型评估结果与具体样本联动。

值得借鉴：

- 不只报告“重复了多少”，还要提供重复组排序、相似度、保留建议和跨 split 泄漏提示。
- 将模型评估指标下沉到样本级，例如 false positive、false negative、IoU、mistakenness，再从统计图直接回到样本。
- 近重复与唯一性属于高价值研究数据整理能力，但默认应是可选本地计算，并允许用户提供预计算 embedding。

不建议立即实现：

- 默认下载大模型、强制 GPU、外部向量数据库或自然语言检索不符合当前 MVP 边界。

参考：[FiftyOne Brain](https://docs.voxel51.com/brain/index.html)、[模型评估](https://docs.voxel51.com/user_guide/evaluation.html)、[数据导入不复制原始文件](https://docs.voxel51.com/user_guide/import_datasets.html)。

### 2.4 Datumaro

Datumaro 将数据流抽象为 Extractor → Dataset → Converter，中间挂接过滤、转换、统计、验证、合并和比较；默认尽量惰性读取媒体，并记录 patch 以减少不必要写入。

值得借鉴：

- 将格式实现收敛为 importer/exporter adapter 注册表，内部统一使用项目自己的 Annotation/Sample 契约。
- 后续增加数据集比较、标签重映射、合并冲突报告和格式验证时，不应继续把条件分支堆进单个 service。
- 媒体默认惰性读取，只有预览、尺寸计算或显式导出媒体时才打开原始文件。

参考：[Datumaro 介绍](https://open-edge-platform.github.io/datumaro/stable/docs/get-started/introduction.html)、[架构](https://open-edge-platform.github.io/datumaro/latest/docs/explanation/architecture)、[数据集合并](https://open-edge-platform.github.io/datumaro/latest/docs/command-reference/merge.html)。

### 2.5 DVC

DVC 的价值是让数据、处理管线和实验具备可复现版本，并通过内容寻址缓存或远端存储管理大文件，而 Git 只保存轻量描述。

值得借鉴：

- 本项目先实现轻量 `DatasetSnapshot`：记录文件 hash、相对路径、标签、标注、split、导出格式和生成时间。
- 快照默认引用原始文件，不复制原图；后续再提供可选 DVC 集成，而不是自行实现完整的大文件版本控制系统。

参考：[DVC 典型工作流](https://dvc.org/doc/command-reference/)。

## 3. 产品经理视角

### 3.1 最值得实现：质量工作台

目前系统已经能扫描、标注和导出，但“数据是否适合训练”仍需要用户自己判断。质量工作台应该成为数据集详情页的主流程之一。

第一版应覆盖：

- 空标注图片、无类别对象、非法/越界几何、零面积 polygon。
- 同一样本内完全重复或高 IoU 重叠对象。
- train/val/test 之间相同 hash 泄漏。
- 类别分布极不平衡、只出现在单一 split 的类别、极少样本类别。
- 未审核、已拒绝、导出预检阻断项。
- 点击任一问题后进入对应筛选视图或标注页，修复后可重新检查。

这比继续增加更多标注工具更有价值，因为它直接提高训练数据可信度，并复用现有扫描、统计、标注和预检能力。

### 3.2 第二优先：本地任务中心

扫描 5,949 个文件的真实端到端烟测耗时 8.581 秒，该流程还包括内存数据库登记、写入测试标注、六种预检和六种导出。更大的目录会让同步 HTTP 请求明显变长。

任务中心至少需要：

- 状态：queued/running/succeeded/failed/cancelled。
- 进度：已处理/总数、当前阶段、耗时、错误计数。
- 操作：取消、重试、查看结果、清理历史。
- 类型：扫描、缩略图、导入、导出、统计重建、备份。
- 单机默认一个写任务、一个或两个只读/CPU 任务，避免磁盘争用。

### 3.3 第三优先：快照、比较与可复现训练清单

建议新增：

- 创建快照：保存 manifest、annotation revision、label mapping、split、导出配置和文件 hash。
- 比较快照：新增/删除/变更文件，标签和标注变化，split 变化，类别分布变化。
- 从快照导出：保证同一版本能再次生成相同类别映射和训练标签。
- 轻量备份/恢复 SQLite 元数据，并明确备份不包含原图。

### 3.4 第四优先：保存视图与批量操作可逆性

- 保存当前筛选、排序、列/卡片密度和页大小。
- 支持将保存视图设为“标注队列”或“导出范围”。
- 批量更新 split、标签和审查状态前展示影响数量与抽样预览。
- 提供最近一次批量元数据操作撤销；仍不对原始文件执行撤销式移动或删除。

### 3.5 后续高价值能力

- 精确重复 → 跨 split 泄漏 → 可选近重复/唯一性，分三步实施。
- 导入 COCO/YOLO/VOC 标注，形成双向格式通路。
- 导入模型预测并与 ground truth 对比，先支持离线 JSON，不接外部 AI API。
- 数据集比较、标签重映射和合并冲突报告。
- 可选 DVC 集成，只保存指针与版本信息。

## 4. 架构师视角

### 4.1 当前架构判断

当前模块化单体结构适合项目阶段：

- `api/` 保持薄路由。
- `services/` 承担业务逻辑。
- `models/`、`schemas/` 分离数据库与 API 契约。
- React 页面、组件、API、类型分层清楚。
- 原始文件与 SQLite 元数据分离，数据安全边界正确。

因此结论是：**需要局部演进，不需要重写。**

### 4.2 近期需要增加的架构接缝

#### 查询层

建立统一 `SampleQuerySpec`，由 repository/query service 负责：

- SQL 过滤、排序、计数和分页。
- tag join、duplicate 子查询和全文搜索。
- 样本列表、导航、manifest、导出和保存视图共用相同查询语义。

当前 `get_filtered_samples()` 会先把匹配数据全部加载到 Python，再搜索、标签过滤、排序和分页；它是最优先的架构优化点。

#### 本地任务层

新增 `jobs` 表和本地 job runner：

- API 只负责创建任务、查询状态和取消任务。
- worker 不共享 request Session，每个任务独立创建数据库 Session。
- 文件哈希可以有限线程并发，数据库写入保持单写者、批量提交。
- MVP 不需要 Redis/Celery；进程内 runner + 持久化 job 表已经足够。

#### 格式适配层

将导入导出实现逐步收敛为：

```text
AnnotationFormatAdapter
├── precheck(context)
├── import_annotations(source, options)
├── export_annotations(query, options)
└── describe_capabilities()
```

这样新增 COCO/YOLO/VOC 导入或 Datumaro 集成时，不需要继续扩大一个统一条件分支 service。

#### 数据集 revision 与派生缓存

- 数据集元数据、sample、tag、annotation、split 每次成功写入后递增 `dataset_revision`。
- stats、duplicate report、quality report、export precheck 缓存都记录所依据的 revision。
- revision 不匹配时标记过期或后台重建，避免依赖复杂的手工缓存失效规则。

#### 正式迁移

当前启动时列回填适合早期 MVP，但从下一次模型变更开始应引入 Alembic：

- 保留已有数据库升级路径。
- 每个 schema 变化有可审计版本和回滚说明。
- 为未来 SQLite → PostgreSQL 迁移提供稳定边界。

### 4.3 明确不做

- 不拆微服务。
- 不为单用户本地应用引入 Kubernetes、消息中间件或分布式锁。
- 不把原始媒体写进数据库。
- 不把 async 当作文件哈希或图像处理的加速方案；CPU/磁盘任务应进入受限 worker。
- 不在没有查询计划和基准数据前盲目增加大量索引。

## 5. 用户与视觉体验视角

### 5.1 使用体验问题

1. **数据集详情页信息密度偏高。** 统计卡、审查状态、类别摘要、筛选、批量操作、排序和样本卡同时出现，新用户不容易判断下一步应该扫描、体检、标注还是导出。
2. **重要能力隐藏在“更多”中。** 标签体系、导入元数据、manifest/CSV 和训练格式导出混在一个浮层；对研究流程而言“质量检查”和“导出训练数据”应比设置类操作更突出。
3. **全局统计与当前筛选仍需持续强化作用域。** 虽然行为已修正，但卡片和结果区最好明确显示“全数据集”或“当前视图”，避免用户误解统计数字。
4. **长任务缺少持续反馈。** 扫描和导出只有忙碌状态，用户看不到阶段、进度、预计剩余量、是否可取消。
5. **错误信息不够产品化。** 导出向导会显示英文 issue code 和英文后端消息；应提供中文标题、解决建议和“定位样本”操作，技术 code 作为次级信息。
6. **导出向导偏窄且存在长内容内滚动。** 类别多、问题多时信息拥挤；桌面端可改为 720–880px 宽，结果列表独立滚动，底部操作固定。
7. **视图不可复用。** 用户完成一组复杂筛选后无法命名保存，返回数据集或下次启动需要重新设置。
8. **批量操作缺少预览和撤销。** 对 split、标签和审查状态的批量修改需要更强的影响确认。

### 5.2 视觉问题

- 当前大量使用相近的白色、浅灰边框和灰色文字，层级主要依赖边框，重要状态与普通信息的视觉权重接近。
- 圆角、阴影、内边距和图标尺寸分散在组件 class 中，尚未形成明确 token；长期会出现相似但不一致的卡片和弹窗。
- 统计卡数量较多，颜色既承担状态又承担入口含义，建议减少常驻卡片，将低频指标放入“数据健康”面板。
- 样本卡片同时承担预览、选择、详情和标注入口，hover 控件较多；应为主动作提供稳定位置，并保证触屏/键盘用户也能发现。

### 5.3 建议的视觉层级

数据集详情页可调整为：

```text
数据集标题 + 根目录 + 最近扫描状态
主要动作：扫描 / 数据健康 / 开始标注 / 导出
关键健康摘要：阻断问题、待审核、split 泄漏、未标注
当前视图工具栏：搜索、筛选、保存视图、排序
样本网格 / 紧凑列表切换
次级信息：容量、扩展名分布、完整统计
```

设计系统建议：

- 建立语义颜色 token：primary/success/warning/error/info/neutral。
- 统一 4/8px 间距体系、卡片 padding、按钮高度和 16/20/24px 图标规格。
- 保持白色简洁风格，但用字号、字重、留白和区域背景增强层级，不依赖更多颜色。
- Modal 增加焦点陷阱、Esc 关闭、打开后聚焦标题或首个控件；破坏性确认默认聚焦取消。
- Loading、empty、error、stale 四种状态形成统一组件。

## 6. 数据库、延迟与并发设计

### 6.1 当前实际基线

当前代码没有正式 SLA，以下规模是根据实现方式推断出的安全工作区间，而不是已经承诺的上限：

- 使用方式：单机、单用户、一个浏览器会话。
- 建议当前规模：约 5,000–10,000 samples、10 万以内 annotations。
- 并发模型：多个只读请求可以并行；SQLite 写操作实质上应按单写者设计。
- 页面分页：每页 24–200，默认 60，但后端当前仍会先加载全部匹配行再分页。
- 真实基线：`D:\My Datasets\test` 共扫描 5,949 个文件，端到端扫描、内存登记、写入测试标注、六种预检和六种导出耗时 8.581 秒；该数字不能视为纯扫描吞吐量。

当前主要复杂度：

| 路径 | 当前行为 | 复杂度/风险 |
| --- | --- | --- |
| 样本列表 | 全量加载后在 Python 搜索、tag 过滤、排序、切页 | O(N) 内存与 CPU；tag 可能触发额外查询 |
| 相邻导航 | 全量构造当前视图再找前后样本 | O(N)，大数据集每次切图成本上升 |
| 统计 | 全量加载 Sample，再在 Python 聚合 | O(N) 内存；与重复报告重复扫描 |
| 重复报告 | 全量加载并返回所有重复组详情 | 重复多时响应体和序列化成本高 |
| 扫描 | 每轮对所有支持文件重新算 SHA-256 | O(总字节数)，大文件与网络盘延迟明显 |
| 导出 | 全量构造内存对象和 `BytesIO` | 大导出峰值内存高，长时间占用请求线程 |

### 6.2 下一阶段目标规模

| 指标 | Tier A：近期 | Tier B：优化后 | 迁移信号 |
| --- | --- | --- | --- |
| samples/数据集 | 10,000 | 100,000 | 持续超过 100,000 且查询优化后仍超 SLA |
| annotations/数据集 | 100,000 | 1,000,000 | 单次导出/统计无法控制内存或耗时 |
| 活跃用户 | 1 | 1–3 个本地客户端 | 需要真正远程多用户与权限 |
| 并发读 | 4 | 8–16 | 读 p95 因数据库锁或 I/O 持续恶化 |
| 并发写 | 1 | 1 个任务写者 | 业务必须支持多个独立写者 |
| 样本列表 p95 | <150ms | <300ms | SQL 下推和索引后仍不达标 |
| 样本详情/标注读取 p95 | <100ms | <150ms | 单样本对象数异常或查询未命中索引 |
| 缓存统计 p95 | <300ms | <500ms | revision 缓存仍频繁失效或重算 |
| 任务创建反馈 | <300ms | <500ms | 不允许用任务总耗时冒充接口延迟 |

### 6.3 SQLite 并发策略

SQLite 官方 WAL 文档说明 WAL 允许读者与写者并行，但仍只有一个写者；长期活跃读事务还可能阻止 checkpoint。项目应按这个边界设计，而不是把连接池大小等同于写并发能力。

近期建议：

- 启用并测试 `PRAGMA journal_mode=WAL`、`busy_timeout=5000`、`foreign_keys=ON`。
- 评估 `synchronous=NORMAL` 的持久性取舍后再启用，不静默降低安全等级。
- 每个 API 请求、后台任务使用独立 Session，不在线程或进程间共享 Session/连接。
- 一个后台写任务串行提交；读取任务保持短事务，响应结束立即释放 Session。
- 监控 WAL 大小、checkpoint 时间、`database is locked` 次数和写事务耗时。

参考：[SQLite WAL](https://sqlite.org/wal.html)、[SQLite Query Planner](https://www.sqlite.org/queryplanner.html)、[SQLAlchemy SQLite 事务说明](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html)、[SQLAlchemy 连接池](https://docs.sqlalchemy.org/en/20/core/pooling.html)。

### 6.4 优化顺序

#### 第一步：建立基准与观测

- 新增可重复 benchmark：10k/100k synthetic metadata，1/10/100 annotations 每样本。
- 记录接口 wall time、SQL 查询数、返回体大小、峰值内存和锁等待。
- 用 `EXPLAIN QUERY PLAN` 验证关键查询，不凭字段感觉添加索引。
- 基准至少覆盖 list、navigation、stats、duplicates、precheck、export、增量 scan。

#### P1：数据库查询下推

- `COUNT + WHERE + ORDER BY + LIMIT/OFFSET` 在数据库完成。
- tag 用 join/exists；duplicate 用 `GROUP BY file_hash HAVING count(*) > 1` 子查询。
- 样本 tag 使用 eager/select-in loading，避免 N+1。
- 统计改为 SQL 聚合，或按 dataset revision 缓存派生结果。
- 优先评估复合索引：
  - `samples(dataset_id, file_type, created_at)`
  - `samples(dataset_id, file_status, created_at)`
  - `samples(dataset_id, split, relative_path)`
  - `samples(dataset_id, review_status, created_at)`
  - `annotations(sample_id, z_order, id)`
  - `annotations(dataset_id, label)`
- 10 万级深分页再切换 keyset/cursor；不要在 1 万级提前复杂化。

#### P1：扫描优化

- 已登记文件先比较 size + mtime；未变化时跳过 SHA-256。
- 首次扫描和显式“深度校验”才全量 hash。
- 文件 stat/hash 可使用受限线程池，数据库写入通过单写者分批提交。
- 每 500–2,000 条批量提交并持久化进度，具体批次由基准决定。
- 扫描结果按阶段显示：枚举、元数据、hash、数据库更新、缺失检测。

#### P1：导出与缩略图

- 大型 ZIP/JSON 改为临时文件或流式响应，避免完整驻留 `BytesIO`。
- 导出任务固定使用创建时的 query snapshot 和 dataset revision，防止范围漂移。
- 缩略图按内容 hash 缓存，后台懒生成；列表只请求当前页和少量预取。

#### P2：前端服务器状态

- 为 dataset/stats/samples/tags/duplicates 引入统一请求缓存与失效策略，可评估 TanStack Query。
- 筛选变化时取消旧请求，避免慢响应覆盖新视图。
- 统计与重复详情按需加载；详情页首屏不必同时下载完整 duplicate report。
- 网格数量达到数千时仍只渲染当前页；若未来改为无限滚动，再引入虚拟列表。

#### P3：数据库迁移门槛

只有满足以下任一条件才进入 PostgreSQL 方案：

- 明确需要远程多用户、认证、权限和多个并发写者。
- WAL + 查询下推 + 索引 + 短事务后仍频繁出现锁错误。
- 需要多进程 API/worker 同时写同一数据库。
- 100k/1M 目标规模下关键接口持续超过 SLA，且瓶颈已确认在 SQLite 写锁或查询能力。

迁移时保持 SQLModel/SQLAlchemy schema 和 repository 接口稳定，先做双数据库测试，不重写业务 service。

### 6.5 FastAPI 并发边界

当前同步 SQLAlchemy、文件系统和 hash 调用使用普通 `def` 路由是合理的；FastAPI 会将同步路径操作放入线程池。将函数机械改成 `async def` 不会加速同步磁盘或 CPU 工作，反而可能阻塞事件循环。

建议：

- 短同步数据库操作继续使用 `def`。
- 长扫描、hash、缩略图、导入和导出进入本地任务 runner。
- 真正支持 await 的网络 I/O 才使用 `async def`。
- CPU 密集处理采用受限进程/线程 worker；进程 worker 不继承或共享 SQLAlchemy 连接池。

参考：[FastAPI 并发与 async/await](https://fastapi.tiangolo.com/async/)、[SQLAlchemy Engine 与 Pool](https://docs.sqlalchemy.org/en/20/core/engines.html)。

## 7. 推荐实施路线

### Batch D1：质量工作台

- 统一 quality issue schema 与 API。
- 完成空标注、越界、非法几何、重复对象、split hash 泄漏检查。
- 从问题直接跳转到筛选视图或标注对象。

### Batch F1：查询与性能基础

- 建立 benchmark 和接口计时。
- 样本列表/导航 SQL 下推、tag eager loading。
- stats/duplicates SQL 聚合与按需加载。
- 基于查询计划增加复合索引。

### Batch F2：本地任务中心

- jobs 表、runner、进度、取消、重试。
- 先迁移扫描和训练格式导出，再迁移缩略图、导入和备份。

### Batch E1：快照与可复现性

- dataset revision、轻量快照、差异比较。
- metadata backup/restore。
- 导出记录绑定 revision、class map 和 query snapshot。

### Batch E2：研究效率

- 保存视图和标注队列。
- 跨 split 精确重复升级为近重复/唯一性。
- 离线 prediction 导入和样本级评估。

## 8. 验收决策

每个性能批次必须同时满足：

- 功能结果与现有 API 契约一致。
- 原始文件安全边界不变。
- 提供变更前/后的同一数据集基准。
- 记录 p50/p95、峰值内存、SQL 数量和数据规模。
- 优化没有以隐藏 warning、跳过校验或降低事务安全为代价。
