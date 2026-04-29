# Dataset Manager

本项目是一个本地优先的科研数据集管理系统 MVP。原始数据文件保存在本地磁盘，SQLite 只保存数据集、样本、路径、hash、标签、统计等元数据。

## 已实现功能

- FastAPI 后端应用和 SQLite 初始化
- Dataset / Sample / Tag 数据模型
- 本地文件夹扫描，支持图片、视频、CSV
- 自动登记文件大小、扩展名、MIME、SHA256、相对路径
- 样本详情、标签编辑、备注和 split 更新
- 数据集统计和 manifest JSON 导出
- React + TypeScript + Vite + Tailwind 前端
- 数据集列表、创建弹窗、详情页、样本网格、详情侧边栏、搜索筛选

## 目录结构

```text
dataset-manager/
  backend/
    app/
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
4. 重复扫描同一目录时，已登记的相同路径会被跳过。

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
GET    /api/datasets/{id}/samples
GET    /api/samples/{id}
PATCH  /api/samples/{id}
GET    /api/samples/{id}/file
GET    /api/stats/datasets/{id}
GET    /api/datasets/{id}/export-manifest
```

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

## 测试

```bash
cd backend
uv run pytest
```

## MVP 边界

第一版不包含登录、多用户权限、云同步、AI API、桌面端打包、复杂标注工具、向量数据库和分布式任务队列。
