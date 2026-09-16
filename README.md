# Dataset Manager

当前已发布版本：`v0.4.1`；当前外部测试候选：`v0.5.0-rc.1`（应用版本 `0.5.0`，尚未正式发布）

当前开发阶段：快速分拣、批量分拣、普通目录/ZIP 导出及通用标注导入已形成可试用闭环；`v0.5.0-rc.1` 供外部测试，干净 Windows 10/11 x64 虚拟机验收仍待完成。

本项目是一个面向研究人员、小型实验室和隐私敏感场景的本地优先视觉数据集准备工作台。它聚焦“扫描数据 → 整理样本 → 连续标注 → 质量检查 → 导出训练数据”的单机闭环；原始数据文件始终保存在本地磁盘，SQLite 只保存数据集、样本、路径、hash、标签、标注和统计等元数据。

## 产品定位

- 当前支持图片目标检测、多边形分割数据准备、图片分类式标签整理，以及客户图片的 OK/NG 快速分拣、旧目录映射和目录/ZIP 交付；下一步验证异常检测数据准备工作流。
- 产品价值是让个人研究者无需部署团队协作平台，也能安全、直观地获得可训练、可复核、可复现的数据集。
- 视频和 CSV 当前只作为通用样本资产登记与筛选对象，不扩展为视频逐帧标注或表格标注平台。
- MVP 不追求复刻 CVAT / Label Studio 的项目、任务、权限和在线协作体系，也不以增加更多图形工具为主要目标。
- 当前已完成本地任务中心、revision/快照、保存视图、跨 split 精确重复强化，以及快速分拣到目录/ZIP 导出的主流程；下一步开展真实试用并验证异常检测训练模板。近重复与预测回流按真实使用反馈进入后续阶段。详见 [当前 TODO](TODO.md) 和 [分拣与导出设计](docs/quick-sorting-directory-export.md)。

## 已实现功能

- FastAPI 后端应用和 SQLite 初始化
- Dataset / Sample / Tag 数据模型
- 本地文件夹增量扫描，支持图片、视频、CSV；未变化文件按 size + mtime 跳过重复 hash，变化文件受限并行校验并分批写入元数据
- 自动登记文件大小、扩展名、MIME、SHA256、相对路径、文件状态和扫描时间
- 样本详情、标签编辑、备注、split 更新和批量操作
- 独立快速分拣工作区：完全 OK、勉强 OK、NG、待定四种判定，支持键盘连续操作、保存后前进、跳过、单步撤销和会话位置恢复
- 结构化分拣元数据：两级缺陷类型、多类型与主缺陷、轻微/中等/严重程度、备注、判定标准版本、图片或标准变化后的过期提示
- 分拣队列与查询：未分拣、待定、全部图片和当前 split 导航，列表/统计/manifest 可读取分拣状态，详情网格显示分拣摘要
- 批量分拣：对最多 200 张明确选择的图片逐字段保留、设置或清空，缺陷类型可追加/替换；预览逐项差异后单事务提交，任一冲突整批回滚
- 分拣目录导出：按当前层级预览目录、数量、容量与排除原因，后台生成 ZIP 下载或服务器托管目录，并附可追溯清单、冻结配置和报告
- 旧目录映射：分页分析已扫描图片的直接父目录，逐目录映射为 OK/NG/待定及当前启用的细分字段，预览后以后台单事务导入
- 标签体系管理：颜色、描述、层级和别名
- 重复样本识别：按 SHA-256 聚合、解释跨 train/val/test 泄漏、有界分页并定位具体样本
- 样本标签、几何标注进度与审核状态独立；审核状态为未审核、审核中、已通过、已拒绝，几何进度支持未开始、处理中、已完成无目标、已完成有对象
- 数据集体检：集中检查缺失文件、重复样本、未标注样本和划分覆盖
- 异常统计卡：缺失/重复有问题时变色，点击后提供对应筛选或修复入口
- 样本统计卡支持按全部类型、图片、视频快速筛选
- 标签统计卡：展示各标签命中数量、未标注样本数，并支持按标签快速筛选
- 数据集随机/分层划分：支持 train/val/test 比例、是否划出 test、标签分层和固定随机种子；极端比例导致验证集或测试集名额不足时会提示至少需要的名额数量
- 缺失文件修复：单文件重新定位和按新根目录批量重新挂载
- 打开数据集自动扫描设置：进入详情页时可自动执行一次增量扫描
- 样本记录删除：单选/多选删除数据库元数据，不删除本地原始文件
- CSV/JSON 元数据导入：批量写入标签、split、备注和自定义属性
- 通用几何标注导入：LabelMe JSON、YOLO detection/segmentation TXT 和 COCO JSON 共用只读预检、来源/计划指纹、后台任务、替换/追加、取消/重试/回滚；结果直接在标注画布显示
- 数据集统计、manifest JSON、CSV 标签表，以及 LabelMe、COCO detection/segmentation、YOLO detection/segmentation、Pascal VOC 标注导出
- Alembic 安全迁移、数据库完整性预览/显式修复，以及支持进度、取消、重试和重启恢复的本地任务中心
- LabelMe 训练格式异步导出任务：冻结请求参数、应用内临时 ZIP、原子发布、大小/hash、取消/失败清理与文件流下载
- 图片几何标注：矩形、多边形、点、对象类别与属性、撤销/重做、快捷键、连续队列、保存草稿/完成/确认无目标和相邻图片预取
- 数据集 revision、不可变轻量快照、差异比较与历史训练标签重建；快照不复制原图，不能恢复丢失的原始图片
- 保存视图与可复用标注队列；SQLite 元数据备份已提供，完整离线恢复流程仍待补齐
- React + TypeScript + Vite + Tailwind 前端
- Windows x64 免安装便携版：单个本地端口提供页面与 API，双击启动、自动避让端口、避免重复进程，并提供打开数据目录和安全退出入口
- 数据集列表、创建弹窗、详情页、样本网格、详情侧边栏、标签管理、搜索筛选

## 当前阶段：快速分拣与目录导出

目标场景：收到客户图片后，先快速判定合格与否，按需记录缺陷类型/程度，导出算法可读取的图片目录，再对需要的样本做精细标注。复用同一批样本，不要求重新扫描成另一份数据集。

### 已实现的分拣主流程

| 信息 | 当前支持 | 含义 |
|---|---|---|
| 判定 | 未分拣、待确认、OK、NG | 待确认不等于勉强 OK |
| OK 等级 | 可配置为统一 OK，或完全 OK／勉强 OK | 勉强 OK 表示按当前标准仍合格 |
| NG 层级 | 不细分、按缺陷类别、按程度、类别＋程度 | 只显示并校验当前层级需要的字段 |
| 缺陷类型 | 两级类型、可多选、可指定主缺陷 | 启用类别维度后仍可先判 NG、稍后补类型 |
| 缺陷程度 | 轻微、中等、严重、未评估 | 启用程度维度后可独立记录 |
| 判定依据 | 数据集标准与版本、分拣备注 | 区分客户标准，改变标准后提示复查 |

例如“可接受浅划痕”可记录为勉强 OK＋划痕＋轻微；“关键区小裂纹”可记录为 NG＋裂纹＋轻微。程度不会自动决定合格与否。完全 OK 与有效缺陷字段冲突时需要用户明确处理。

当前已提供大图查看与缩放、按配置生成的 1–4 键判定、详细分拣、保存后下一张、空格跳过、会话内单步撤销、位置恢复、相邻图预取和条件更新冲突保护。“分拣层级”面板统一控制操作按钮、详细字段、筛选项、统计卡片和目录结构预览。配置变化保留历史判定并标记待复核；旧策略缺少新字段时沿用原有“细分 OK＋类别和程度”行为。缺陷类型与程度默认不继承上一张。详情页支持对最多 200 张明确选择的图片逐项预览并事务提交批量分拣。分拣不改变几何标注进度、审核状态或 split。快照分拣差异和保存视图扩展仍在 TODO 中。

### 已实现的旧目录映射

- 数据集详情“管理与导出”提供“映射旧目录”向导，只分析已经扫描登记的图片及其直接父目录，不扫描新位置，也不操作原始文件。
- 用户逐目录选择不导入、OK、NG 或待定；字段随当前分拣层级变化。常见目录名只能生成待确认草稿，细分 OK 下普通 `OK/` 仍必须明确选择完全或勉强。
- 默认只填未分拣样本；显式覆盖已有判定时保留原备注。预览列出将写入、已一致、保留已有、未映射和不可用样本，并冻结 revision、配置、样本版本与文件 hash。
- 后台任务在单个 SQLite 事务中写入，任一冲突整批回滚。任务中心支持取消、失败说明、重试和结果摘要。

### 已实现的目录/ZIP 导出

- 导出向导可选择全部图片、当前筛选、当前 split 或已选样本，并选择 ZIP 下载或服务器托管目录。当前分拣层级是唯一目录规则：未分级旧 OK 使用 `ok/ungraded`，缺少类型/程度分别使用 `unknown`/`ungraded`。
- 预检会冻结样本、目标路径、源文件 hash、数据集 revision 和分拣配置，分页展示目录计数、总容量、来源到目标的映射及排除原因。计划一小时内有效；数据或配置改变后必须重新预检。
- 多缺陷图片默认只导出一份，按显式主缺陷归类；没有类型为 unknown、没有程度为 ungraded。待确认/未分拣默认排除，可选择单独导出。
- 后台任务提供进度、取消、重试和失败说明；复制时流式校验 SHA-256。ZIP 从任务中心下载，服务器目录写入应用托管的 `storage/directory-exports`，界面明确显示后端机器路径。
- 导出只复制原图，不移动、不覆盖、不合并已有目录。目录先写入同一输出根的临时工作区，再原子发布；ZIP 沿用任务产物的原子发布。两种产物都附 `manifest.jsonl`、`export-config.json` 和 `export-report.json`。
- 后续异常检测模板默认仅完全 OK 进入正常训练；勉强 OK 单独处理，按工件/采集组划分，NG 不进入纯正常训练。具体算法版本的数据加载验证通过后才声明可直接使用。

### 开发顺序

1. 完成 Q1/Q2 剩余项：快照分拣差异、旧普通标签映射评估和压力/窄屏验收。
2. Q4：异常检测训练模板、分组划分和实际数据加载验证。
3. Q5：真实用户对照试用，修复阻断并根据复用意愿决定后续能力。

Q3 后即可先行试用。未来模型能力优先从离线预测导入起步；模型运行环境独立，平台统一负责数据选择、结果查看和人工复核。本阶段不接模型 API、不建设团队权限系统。

详细数据模型、接口、文件级改动与验收条件见 [产品与开发设计](docs/quick-sorting-directory-export.md)，执行状态见 [TODO](TODO.md)。

## Windows x64 便携版

发布包解压后双击 `DatasetManager.exe`，程序就绪时自动打开浏览器。最终用户无需安装 Python 或 Node.js。程序文件保留在解压目录；所有运行数据统一写入 `%LOCALAPPDATA%\DatasetManager`：

| 路径 | 内容 |
|---|---|
| `database/app.db` | SQLite 元数据 |
| `database/backups/` | 升级前数据库备份 |
| `config/` | 本机配置与运行状态 |
| `logs/` | 启动与运行日志 |
| `cache/` | 便携版缓存保留目录 |
| `storage/` | 缩略图、任务产物及服务器目录导出 |
| `exports/` | 面向用户的导出保留目录 |

再次双击会打开已运行的服务，不会启动第二个后端。默认端口 `8765` 被占用时会在有限端口范围内自动选择可用端口。页面左下角“便携版”菜单提供“打开数据目录”和“安全退出”。异常退出留下的运行状态会在下次启动时自动替换。

升级时先安全退出，再以新版程序文件覆盖原解压目录。应用数据位于 `%LOCALAPPDATA%`，不会随程序覆盖而丢失；需要迁移数据库时，启动器先创建校验通过的备份，再原子升级。启动、升级、退出和卸载程序目录均不复制、移动、重命名或删除用户导入的原始数据。

构建与验收说明见 [packaging/windows/README.md](packaging/windows/README.md)。构建产物为 `dist/DatasetManager-windows-x64-portable.zip`；外部测试候选包采用带版本号的副本 `dist/DatasetManager-v0.5.0-rc.1-windows-x64-portable.zip`，随包提供 SHA-256 校验文件。

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
POST   /api/datasets/{id}/directory-export-previews
GET    /api/datasets/{id}/directory-export-previews/{plan_id}
POST   /api/datasets/{id}/directory-export-jobs
GET    /api/datasets/{id}/triage-directory-sources
POST   /api/datasets/{id}/triage-directory-mapping-previews
GET    /api/datasets/{id}/triage-directory-mapping-previews/{plan_id}
POST   /api/datasets/{id}/triage-directory-mapping-jobs
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

几何标注导入入口位于数据集详情“其他操作 → 导入标注”。YOLO 从 `data.yaml` 或 `classes.txt` 读取类别并把归一化 bbox / polygon 转为像素坐标；COCO 把 bbox 与 polygon segmentation 转为画布对象。pose、OBB、RLE mask 等暂不支持内容会显示结构化诊断。完整交互、格式和安全边界见 [通用标注导入设计](docs/annotation-import-formats.md)。

- `manifest` 是系统原生审计清单，包含路径、hash、文件状态、标签、split 和自定义元数据。
- `CSV 标签表` 面向样本级标签和表格流转，适合人工检查或再次导入。
- `标注训练格式` 提供 LabelMe、COCO detection/segmentation、YOLO detection/segmentation 和 Pascal VOC 真实导出。
- 训练格式导出会先运行预检，展示不兼容对象、有损几何转换、空标注和类别映射；error 会阻断下载，warning 允许确认后继续。
- v0.4.1 的导出包只包含标签、配置和报告，不复制原始图片，也不在原始数据目录生成旁车文件。
- “分拣目录导出”会显式复制图片到新的服务器托管目录或 ZIP，并附完整清单；它与现有几何标签导出使用不同入口和任务类型。

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

## 开发与规划文档

- [当前 TODO](TODO.md)：当前批次、完成门槛和后续池。
- [快速分拣与目录导出设计](docs/quick-sorting-directory-export.md)：本阶段产品规则、数据/API、实现边界和验证策略。
- [旧目录映射设计](docs/triage-directory-mapping.md)：历史目录到结构化分拣结果的交互、冻结计划、原子写入和验收边界。
- [版本变更](CHANGELOG.md) 与 [人工验收](ACCEPTANCE_TESTS.md)：已实现行为与验证记录。
- [v0.4.1 TODO 归档](docs/todo-v0.4.1-archive.md)：旧阶段全文；旧 roadmap 仅供背景参考，不覆盖当前 TODO。
