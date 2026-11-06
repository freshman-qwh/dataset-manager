# Dataset Manager

本地工业图片数据准备与快速验证工作台。把客户或产线图片整理成可信的正常/异常样本，再导出独立训练数据包，或在本机建立可复查的异常检测基线。

原始文件保留在本地磁盘；扫描、分拣、标注和记录删除只管理元数据。导出时按用户选择复制到新目录或 ZIP，不改写原图。

## 第一次使用

**先浏览图片**：把各本地目录分别新建为数据集并扫描一次，首页进入“本地浏览”。左侧快速切换数据集，右侧按文件夹打开或平铺查看子目录图片；点击图片可放大、左右切图。无需先分拣或配置算法环境。操作见 [本地浏览指南](docs/local-browsing.md)。

**按项目持续积累**：探针、绿油锡分别创建项目，数据集关联项目；每次“添加图片”可选择或新建采集批次。MVTec AD、VisA 自动识别对象类别、官方划分与 mask，导入前可预览，原图与 mask 保留原位置。旧图片可显式补充空的识别信息。见 [项目、类别与批次](docs/project-category-batch.md)。

**日常查看与介绍**：首页工作台可继续上次浏览、查看最近打开和置顶常用数据集。在本地浏览中，可自动生成数据集名片并下载 PNG，或按同一对象类别、采集批次查看正常与缺陷对照。操作见 [日常浏览与对照](docs/daily-tools.md)。

1. **新建项目并扫描图片**：工业场景选择“工业异常检测”；也可先体验合成示例熟悉操作。
2. **快速分拣**：确认正常、异常与待定。完全 OK 是正常拟合候选；临界、过期或不确定样本先复核。图像级流程无需先画框或创建普通标签。
3. **填写工件/采集组和批次**：同一工件的多角度、连拍图属于同组，避免相似图同时进入训练和评估。
4. **选择交付目标**：需要交给算法同事时准备异常检测数据包；需要先看基线时进入快速验证，检查数据方案后确认运行。
5. **复核并复用**：查看需人工确认的图片，保存判断。第二批可复用同一模型、ROI 和冻结阈值，不必重新拟合。

详细操作见 [工业试用指南](docs/industrial-trial-guide.md) 与 [快速验证指南](docs/quick-validation-guide.md)。合成示例仅用于熟悉流程，不能证明真实产线效果。

## 功能如何选择

首页的“数据集图书馆”收录 MVTec AD、VisA、Real-IAD 等工业视觉异常检测资源，提供官方概览图、用途和下载入口；与已登记的本地数据集分开管理。完整来源及获取说明见 [图书馆目录](docs/anomaly-dataset-library.md)。

| 需求 | 使用入口/能力 | 使用条件 |
| --- | --- | --- |
| 查看分散、嵌套的本地图片目录 | 本地浏览、文件夹导航、平铺看图、大图预览 | 先登记并扫描目录，原文件保留原位置 |
| 整理正常/异常图片 | 扫描、快速分拣、旧目录映射、工件分组 | 工业主流程，无需算法环境 |
| 交付独立训练/验证/测试数据 | 异常检测数据包、目录或 ZIP、可追溯清单 | 纯正常训练，采集组隔离，检查纳入与排除原因 |
| 先看本机异常检测基线 | 快速验证、热图、人工复核、同模型第二批 | 可选独立 CPU 环境，当前适配 Anomalib 2.7.0 的 PaDiM/PatchCore |
| 准备检测/分割/分类数据 | 通用项目、几何标注、标签与格式导入导出 | 按需使用；可选 SAM 辅助不影响基础功能 |
| 检查历史与维护数据 | 保存视图、快照/差异、任务中心、备份恢复 | 辅助流程，原图需另行保留 |

产品面向个人研究者、小型实验室和需要本地处理工业图片的用户。视频与 CSV 可登记为通用样本，当前不提供视频逐帧或表格标注。团队权限、云同步、在线模型服务与分布式训练不在当前范围。完整取舍见 [产品定位与功能范围](docs/product-scope.md)。

## 当前源码与交付边界

- 当前发行准备采用 `v0.5.0-rc.3` 预发行标记，包含工作台、名片、对照以及本地浏览和项目/类别/批次管理。下载与实际验收范围以 [GitHub Releases](https://github.com/freshman-qwh/dataset-manager/releases) 的对应条目及包内 `build-manifest.json` 为准。
- 应用内版本为 `0.5.0`。当前源码已包含工业数据准备与 Q1–Q5 快速验证；状态看 [TODO](TODO.md)，已实现变化看 [CHANGELOG](CHANGELOG.md)。
- 2026-10-30 的 [工业便携候选](docs/industrial-trial-delivery-2026-10-30.md) 只包含当日交付能力，**不包含后续快速验证页面**。源码升级不会自动更新已有 ZIP。
- [2026-11-01 验证记录](docs/quick-validation-verification-2026-11-01.md) 是当时的本机工程证据。独立干净 Windows 10/11 和真实工业用户的两批数据复用仍待外部验收；没有正式产线效果结论。
- 图像级协议不生成像素掩码或像素指标。算法环境、预训练权重缓存、原图与历史下载包不属于元数据备份范围。

开发入口见 [开发工作流](docs/development-workflow.md)，所有指南、契约与历史记录见 [文档导航](docs/README.md)。

## Linux 与 macOS

基础 Web 应用使用 Python、SQLite 和浏览器，前端构建结果可复用。当前便携启动器的单实例锁、默认数据目录和“打开数据目录”仍依赖 Windows；现有 ZIP 不适用于 Linux/macOS。

后续可先验证 Linux x86_64 和 macOS Apple Silicon 的源码流程，再分别构建原生包并验收启动、恢复、中文路径和外接磁盘。Linux 需要确定发行版/系统库基线；macOS 还需处理应用封装、签名和公证。可选异常检测算法环境使用当前 Windows 锁文件，不能随基础 Web 能力一起宣称跨平台已验证。

## Windows x64 便携版

便携包解压后双击 `DatasetManager.exe`，程序就绪时自动打开浏览器。基础应用无需安装 Python 或 Node.js；本地快速验证另需算法环境，并以实际包的能力清单为准。程序文件保留在解压目录；默认工作区写入 `%LOCALAPPDATA%\DatasetManager`：

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

构建与验收说明见 [packaging/windows/README.md](packaging/windows/README.md)。默认构建产物为 `dist/DatasetManager-windows-x64-portable.zip`；历史通用候选为 `v0.5.0-rc.1`。工业候选的文件名、源码和 SHA-256 以 [对应交付记录](docs/industrial-trial-delivery-2026-10-30.md) 为准。

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
npm ci
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
2. 进入数据集详情页，点击“添加图片”，确认目录后扫描。
3. 后端只读取文件元数据和内容 hash，不移动、不重命名、不删除原始文件。
4. 重复扫描同一目录时会做增量同步，识别新增、变更、未变和缺失文件。
5. 为避免误扫整盘，后端会拒绝扫描磁盘根目录或文件系统根目录。

支持的 MVP 文件类型：

- 图片：`.jpg`、`.jpeg`、`.png`、`.bmp`、`.tif`、`.tiff`、`.webp`、`.gif`
- 视频：`.mp4`、`.avi`、`.mov`、`.mkv`、`.webm`
- 表格：`.csv`

## REST API

API 使用 `/api` 前缀，包含数据集/样本、分拣/分组、几何标注、训练导出、快速验证、任务和系统维护。以运行中后端的 `http://127.0.0.1:8000/docs` 为完整接口入口；相关 schema 和行为契约见 [文档导航](docs/README.md)。

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

训练划分建议的确认回执需要 `20260929_0008` 迁移；旧数据库可先预览，确认写入前请按上述流程升级。便携版启动器会在启动前执行有备份的迁移。

数据集列表右上角的“数据库维护”提供只读完整性检查。孤立元数据默认不选择；必须先到达当前 migration head，再选择项目、生成最新预览、输入动态确认文本，系统才会在创建可恢复备份后清理 SQLite 元数据。该流程不会删除原始文件。

## 开发、验证与规划

- [开发工作流](docs/development-workflow.md)：安装、启动、按变更验证、界面验收隔离、交接方法。
- [根 AGENTS](AGENTS.md)：共同约束；[后端](backend/AGENTS.md)、[前端](frontend/AGENTS.md)、[文档](docs/AGENTS.md) 规则仅补充各自差异。
- [TODO](TODO.md)：当前优先级与剩余范围；[CHANGELOG](CHANGELOG.md)：已交付变化；[人工验收](ACCEPTANCE_TESTS.md)：可执行路径与通过标准。
- [文档导航](docs/README.md)：操作指南、设计契约和带日期的历史证据。旧 roadmap 不覆盖当前 TODO。
