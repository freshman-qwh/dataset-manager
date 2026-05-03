# Dataset Manager / 科研数据集管理系统

这是一个本地优先的科研数据集管理系统 MVP。后端使用 FastAPI + SQLModel + SQLite，前端使用 React + TypeScript + Vite + Tailwind CSS。

## 快速启动

后端：

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

前端：

```bash
cd frontend
npm install
npm run dev
```

访问：

```text
http://127.0.0.1:5173
```

API 文档：

```text
http://127.0.0.1:8000/docs
```

## 当前功能

- 创建和浏览数据集
- 增量扫描本地文件夹
- 登记图片、视频、CSV 样本
- 自动保存文件大小、扩展名、hash、相对路径、文件状态和扫描时间
- 样本网格预览
- 样本详情侧边栏
- 标签、备注、split 编辑和批量操作
- 标签体系管理：颜色、描述、层级和别名
- 重复样本识别：按 hash 检测重复文件
- 审查状态底层字段：未标注、审查中、已通过、已拒绝
- 数据集体检：集中检查缺失文件、重复样本、未标注样本和划分覆盖
- 异常统计卡：缺失/重复有问题时变色，点击后提供对应筛选或修复入口
- 样本统计卡支持按全部类型、图片、视频快速筛选
- 标签统计卡：展示各标签命中数量、未标注样本数，并支持按标签快速筛选
- 数据集随机/分层划分：支持 train/val/test 比例、是否划出 test、标签分层和固定随机种子；极端比例导致验证集或测试集名额不足时会提示至少需要的名额数量
- 缺失文件修复：单文件重新定位和按新根目录批量重新挂载
- 打开数据集自动扫描设置：进入详情页时可自动执行一次增量扫描
- 样本记录删除：单选/多选删除数据库元数据，不删除本地原始文件
- 元数据导入：从 CSV/JSON 批量导入标签、split、备注和自定义属性
- 搜索、文件类型筛选、标签筛选
- 数据集统计卡片，包含 train/val/test 和重复样本统计
- manifest JSON 导出、CSV 标签表下载，以及 COCO/YOLO 格式骨架

## 元数据导入格式

CSV 示例：

```csv
relative_path,tags,split,notes,quality
images/a.png,"cat;review",train,"good sample",high
```

JSON 示例：

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

支持按 `sample_id`、`relative_path`、`absolute_path`、`filename`、`file_hash` 匹配样本。导入只更新已扫描登记的样本；只修改扫描目录不会自动登记文件，需要先执行扫描。`relative_path` 相对于数据集扫描目录；`absolute_path` 会做路径归一化，兼容 Windows 下的 `D:/...` 和 `D:\...` 写法。若绝对路径位于数据集扫描目录下，系统会同时尝试转换为相对路径匹配。除匹配字段、`tags`、`split`、`notes` 外，其余字段会写入样本自定义元数据。

## 导出说明

`manifest` 是系统原生清单；`CSV 标签表` 是当前最实用的样本级标签导出。COCO/YOLO 目前只是格式骨架，因为完整标准导出需要先实现 bbox、segmentation 等标注数据模型。前端导出会先显示预览弹窗，确认后再下载文件。

## 删除与修复边界

- 删除样本记录只删除 SQLite 中的样本元数据和标签关联，不删除本地原始文件。
- 缺失文件修复只更新数据库中的路径、hash、大小、类型和文件状态，不移动、不重命名、不覆盖本地文件。
- 批量修复缺失文件时，系统按样本 `relative_path` 在新根目录下查找文件。
- 审查状态作为底层字段保留，当前高频工作流优先使用数据集体检、标签覆盖和划分规划。

## 数据安全

扫描过程只读取文件，不会移动、重命名、删除或覆盖原始数据。SQLite 只保存元数据，不保存大文件内容。
