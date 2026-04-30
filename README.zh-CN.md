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

## 数据安全

扫描过程只读取文件，不会移动、重命名、删除或覆盖原始数据。SQLite 只保存元数据，不保存大文件内容。
