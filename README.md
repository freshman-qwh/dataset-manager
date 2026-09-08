# Dataset Manager

当前版本：`v0.4.1`

本项目是一个面向研究人员、小型实验室和隐私敏感场景的本地优先视觉数据集准备工作台。它聚焦“扫描数据 → 整理样本 → 连续标注 → 质量检查 → 导出训练数据”的单机闭环；原始数据文件始终保存在本地磁盘，SQLite 只保存数据集、样本、路径、hash、标签、标注和统计等元数据。

## 产品定位

- 核心任务是图片目标检测与多边形分割数据准备，兼顾图片分类式标签整理。
- 产品价值是让个人研究者无需部署团队协作平台，也能安全、直观地获得可训练、可复核、可复现的数据集。
- 视频和 CSV 当前只作为通用样本资产登记与筛选对象，不扩展为视频逐帧标注或表格标注平台。
- MVP 不追求复刻 CVAT / Label Studio 的项目、任务、权限和在线协作体系，也不以增加更多图形工具为主要目标。
- 当前阶段已完成本地任务中心、revision/快照、保存视图和跨 split 精确重复强化；下一步评估不依赖外部 AI 的近重复/唯一性契约。详细计划见 `TODO.md` 与 `docs/post-ux-d-roadmap.md`。

## 已实现功能

- FastAPI 后端应用和 SQLite 初始化
- Dataset / Sample / Tag 数据模型
- 本地文件夹增量扫描，支持图片、视频、CSV；未变化文件按 size + mtime 跳过重复 hash，变化文件受限并行校验并分批写入元数据
- 自动登记文件大小、扩展名、MIME、SHA256、相对路径、文件状态和扫描时间
- 样本详情、标签编辑、备注、split 更新和批量操作
- 标签体系管理：颜色、描述、层级和别名
- 重复样本识别：按 SHA-256 聚合、解释跨 train/val/test 泄漏、有界分页并定位具体样本
- 审查状态底层字段：未标注、审查中、已通过、已拒绝
- 数据集体检：集中检查缺失文件、重复样本、未标注样本和划分覆盖
- 异常统计卡：缺失/重复有问题时变色，点击后提供对应筛选或修复入口
- 样本统计卡支持按全部类型、图片、视频快速筛选
- 标签统计卡：展示各标签命中数量、未标注样本数，并支持按标签快速筛选
- 数据集随机/分层划分：支持 train/val/test 比例、是否划出 test、标签分层和固定随机种子；极端比例导致验证集或测试集名额不足时会提示至少需要的名额数量
- 缺失文件修复：单文件重新定位和按新根目录批量重新挂载
- 打开数据集自动扫描设置：进入详情页时可自动执行一次增量扫描
- 样本记录删除：单选/多选删除数据库元数据，不删除本地原始文件
- CSV/JSON 元数据导入：批量写入标签、split、备注和自定义属性
- 数据集统计、manifest JSON、CSV 标签表，以及 LabelMe、COCO detection/segmentation、YOLO detection/segmentation、Pascal VOC 标注导出
- Alembic 安全迁移、数据库完整性预览/显式修复，以及支持进度、取消、重试和重启恢复的本地任务中心
- LabelMe 训练格式异步导出任务：冻结请求参数、应用内临时 ZIP、原子发布、大小/hash、取消/失败清理与文件流下载
- React + TypeScript + Vite + Tailwind 前端
- 数据集列表、创建弹窗、详情页、样本网格、详情侧边栏、标签管理、搜索筛选

## 目录结构

```text
dataset-manager/
  backend/
    migrations/
    app/
      cli/
      api/
      core/
      models/
      schemas/
      services/
      utils/
      main.py
    tests/
    pyproject.toml
  frontend/
    src/
      api/
      components/
      hooks/
      pages/
      styles/
      types/
    package.json
  database/
  storage/
  README.md
```

## 后端启动

推荐使用 `uv`：

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

也可以使用普通虚拟环境：

```bash
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

后端地址：

```text
http://127.0.0.1:8000
```

API 文档：

```text
http://127.0.0.1:8000/docs
```

## 前端启动

```bash
cd frontend
npm install
npm run dev
```

前端地址：

```text
http://127.0.0.1:5173
```

如需修改后端地址，可在 `frontend/.env` 中设置：

```text
VITE_API_BASE_URL=http://127.0.0.1:8000/api
```

## 数据扫描方式

1. 在前端创建数据集，可填写本地扫描目录。
2. 进入数据集详情页，点击“扫描”。
3. 后端只读取文件元数据和内容 hash，不移动、不重命名、不删除原始文件。
4. 重复扫描同一目录时会做增量同步，识别新增、变更、未变和缺失文件。
5. 为避免误扫整盘，后端会拒绝扫描磁盘根目录或文件系统根目录。

支持的 MVP 文件类型：

- 图片：`.jpg`、`.jpeg`、`.png`、`.bmp`、`.tif`、`.tiff`、`.webp`、`.gif`
- 视频：`.mp4`、`.avi`、`.mov`、`.mkv`、`.webm`
- 表格：`.csv`

## REST API

```text
GET    /api/datasets
POST   /api/datasets
GET    /api/datasets/{id}
PATCH  /api/datasets/{id}
DELETE /api/datasets/{id}
POST   /api/datasets/{id}/scan
POST   /api/datasets/{id}/scan-jobs
POST   /api/datasets/{id}/annotation-export-jobs
GET    /api/datasets/{id}/samples
PATCH  /api/datasets/{id}/samples/batch
POST   /api/datasets/{id}/samples/delete
POST   /api/datasets/{id}/repair-missing
POST   /api/datasets/{id}/split-plan
GET    /api/datasets/{id}/duplicates
GET    /api/datasets/{id}/tags
POST   /api/datasets/{id}/tags
POST   /api/datasets/{id}/import-metadata
GET    /api/samples/{id}
PATCH  /api/samples/{id}
DELETE /api/samples/{id}
PATCH  /api/samples/{id}/repair
GET    /api/samples/{id}/file
GET    /api/samples/{id}/preview
PATCH  /api/tags/{id}
DELETE /api/tags/{id}
GET    /api/stats/datasets/{id}
GET    /api/datasets/{id}/export-manifest
GET    /api/datasets/{id}/export-template
GET    /api/jobs/{id}/artifact
GET    /api/directories
GET    /api/system/database-integrity
POST   /api/system/database-integrity/repair-preview
POST   /api/system/database-integrity/repair
GET    /api/jobs
POST   /api/jobs
GET    /api/jobs/{id}
POST   /api/jobs/{id}/cancel
POST   /api/jobs/{id}/retry
```

## 元数据导入格式

CSV 至少需要包含当前选择的匹配列，例如：

```csv
relative_path,tags,split,notes,quality
images/a.png,"cat;review",train,"good sample",high
```

JSON 可以是数组，也可以是包含 `samples` 数组的对象：

```json
[
  {
    "relative_path": "images/a.png",
    "tags": ["cat", "review"],
    "split": "train",
    "notes": "good sample",
    "quality": "high"
  }
]
```

支持的匹配列：`sample_id`、`relative_path`、`absolute_path`、`filename`、`file_hash`。导入只更新已扫描登记的样本；只修改扫描目录不会自动登记文件，需要先执行扫描。`relative_path` 相对于数据集扫描目录；`absolute_path` 会做路径归一化，兼容 Windows 下的 `D:/...` 和 `D:\...` 写法。若绝对路径位于数据集扫描目录下，系统会同时尝试转换为相对路径匹配。除匹配列、`tags`、`split`、`notes` 外，其余字段会写入样本自定义元数据。

## 导出说明

- `manifest` 是系统原生审计清单，包含路径、hash、文件状态、标签、split 和自定义元数据。
- `CSV 标签表` 面向样本级标签和表格流转，适合人工检查或再次导入。
- `标注训练格式` 提供 LabelMe、COCO detection/segmentation、YOLO detection/segmentation 和 Pascal VOC 真实导出。
- 训练格式导出会先运行预检，展示不兼容对象、有损几何转换、空标注和类别映射；error 会阻断下载，warning 允许确认后继续。
- 导出包只包含标签、配置和报告，不复制原始图片，也不在原始数据目录生成旁车文件。

## 删除与修复边界

- 删除样本记录只删除 SQLite 中的样本元数据和标签关联，不删除本地原始文件。
- 缺失文件修复只更新数据库中的路径、hash、大小、类型和文件状态，不移动、不重命名、不覆盖本地文件。
- 批量修复缺失文件时，系统按样本 `relative_path` 在新根目录下查找文件。

## 配置

根目录 `.env.example` 提供默认配置：

```text
APP_NAME=Dataset Manager
APP_ENV=dev
DATABASE_URL=sqlite:///../database/app.db
STORAGE_ROOT=../storage
HOST=127.0.0.1
PORT=8000
```

SQLite 数据库默认写入 `database/app.db`。原始数据建议放在 `storage/datasets/` 或用户指定的本地目录。

## 数据库迁移与备份

正式 schema 迁移使用 Alembic，但不会在应用启动时自动替换实际数据库。先查看状态或创建在线只读备份：

```bash
cd backend
python -m app.cli.database status --database ../database/app.db
python -m app.cli.database backup --database ../database/app.db --backup-dir ../database/backups
```

升级前必须停止后端和所有数据库使用者。升级命令会先创建并校验备份，再在临时副本中迁移；只有迁移、版本检查和 SQLite 校验全部成功后才原子替换目标数据库：

```bash
python -m app.cli.database upgrade --database ../database/app.db --backup-dir ../database/backups
```

如果命令报告数据库占用或存在 WAL/SHM/journal 侧车文件，先停止相关进程，不要手工删除仍在使用的侧车文件。迁移失败时原库保持不变，可从命令返回的备份路径恢复。完整边界和验收步骤见 `docs/database-migrations.md` 与 `ACCEPTANCE_TESTS.md`。

数据集列表右上角的“数据库维护”提供只读完整性检查。孤立元数据默认不选择；必须先到达当前 migration head，再选择项目、生成最新预览、输入动态确认文本，系统才会在创建可恢复备份后清理 SQLite 元数据。该流程不会删除原始文件。

## 测试

```bash
cd backend
uv run pytest
```

## MVP 边界

第一版不包含登录、多用户权限、云同步、AI API、桌面端打包、复杂标注工具、向量数据库和分布式任务队列。
