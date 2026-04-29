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
- 扫描本地文件夹
- 登记图片、视频、CSV 样本
- 自动保存文件大小、扩展名、hash、相对路径
- 样本网格预览
- 样本详情侧边栏
- 标签、备注、split 编辑
- 搜索、文件类型筛选、标签筛选
- 数据集统计卡片
- manifest JSON 导出

## 数据安全

扫描过程只读取文件，不会移动、重命名、删除或覆盖原始数据。SQLite 只保存元数据，不保存大文件内容。
