# 开发与验证工作流

适用于当前源码，更新于 2026-11-10。稳定约束见根 [AGENTS.md](../AGENTS.md)；本页集中维护执行方法，避免在各级规则和 README 中复制整套命令。

## 开始任务

1. 在仓库根运行 `git status --short --branch`，记录已有修改和未跟踪产物。不要清理来历不明的文件。
2. 读取根及相关目录 `AGENTS.md`。行为或范围任务读 [TODO](../TODO.md) 顶部当前主线、changelog 最新条目与对应验收步骤；从 [文档导航](README.md) 找相关契约，再读实现。
3. 用一句话说明用户要完成的任务、影响页面/API、验证方式。把可独立检查的前后端或文档工作分开实施，避免同时改相同文件。
4. Bug 先保存复现证据并定位根因。设计/界面优化先看真实状态、实际操作与源码，再决定修改；不要只根据组件名称判断功能无用。

## 安装与启动

基础应用要求 Python 3.11+、Node.js 与 npm。优先使用项目虚拟环境，算法依赖按 [快速验证指南](quick-validation-guide.md) 单独管理。

分别打开两个终端，从仓库根执行：

```powershell
cd backend
uv sync
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

```powershell
cd frontend
npm ci
npm run dev
```

后端默认 `http://127.0.0.1:8000`，API 文档为 `/docs`。前端默认 `http://127.0.0.1:5173`，Vite 将 `/api` 代理到后端。没有启动服务时，不把这些默认值报告成当前可用地址。

启动前检查已有服务；已有进程可用时复用。前台终端用 `Ctrl+C` 停止自己启动的服务；后台进程记录 PID/日志并按 PID 停止，不按端口盲目结束未知进程。Windows `Start-Process` 使用 `-WindowStyle Hidden`。

### 本地配置

[`.env.example`](../.env.example) 列出了数据库路径、存储目录和 CORS 等配置项。默认数据库和应用存储目录分别为仓库内的 `database/app.db` 和 `storage/`。后端依次读取根目录的 `.env` 和 `backend/.env`，后者可以覆盖同名设置。

如果前端需要直接访问自定义后端地址，在 `frontend/.env` 中填写 `VITE_API_BASE_URL` 后重启 Vite。例如，后端监听 `127.0.0.1:8001` 时使用以下配置，并确认后端的 `CORS_ORIGINS` 允许当前前端来源。

```dotenv
VITE_API_BASE_URL=http://127.0.0.1:8001/api
```

### 界面验收隔离

- 优先使用合成示例或独立测试工作区，不改真实项目的判定、分组、split 来演示 UI。
- 隔离后端可设置 `DATABASE_URL=sqlite:///绝对路径/测试目录/database/app.db`、`STORAGE_ROOT=绝对路径/测试目录/storage`。先检查根与后端 `.env`：后端 `.env` 会覆盖同名设置；不要改用户配置来省略这一步。
- 修改服务端口需同步 Vite 代理、API 地址和 CORS。截图、日志和临时数据不提交，保留路径供复核。

## 验证矩阵

先做与变更直接相关的检查，再根据共享影响扩大。历史通过次数不能替代本轮输出。

| 修改类型 | 必要检查 | 扩大条件 |
| --- | --- | --- |
| 纯文档 | 链接/命令/范围核对，`git diff --check` | 改变实际启动或维护流程时验证涉及命令 |
| 前端样式、文案、入口 | `npm run build`；受影响页面的真实浏览器检查 | 涉及公共组件时同时检查工业/通用流程与窄屏 |
| 前端状态或交互 | 构建、关键操作、空/错/加载/禁用状态 | 涉及队列时检查保存后推进、切换与过期响应 |
| 后端局部行为 | `compileall app tests`、相关 pytest | 接口/模型共享时检查相关调用链 |
| 迁移、任务、存储、导出/恢复 | 聚焦回归后完整后端测试 | 交付包变化另跑对应真实 ZIP 验收 |
| API 契约变化 | 后端检查、前端构建及实际请求路径 | 跨端旧状态、版本冲突与兼容路径 |

后端（从 `backend/` 执行）：

```powershell
.\.venv\Scripts\python.exe -m compileall app tests
New-Item -ItemType Directory -Force -Path .\.tmp | Out-Null
$env:TMP = (Resolve-Path .\.tmp).Path
$env:TEMP = (Resolve-Path .\.tmp).Path
.\.venv\Scripts\python.exe -m pytest --basetemp .\.tmp\pytest -p no:cacheprovider tests/相关测试文件.py
```

最后一行替换为本任务的实际测试文件；完整回归删除该文件参数。`--basetemp` 会清理目标目录，只用于专用测试临时目录。虚拟环境缺 pytest 时先 `uv sync`，不要向系统 Python 盲装依赖。

前端（从 `frontend/` 执行）：

```powershell
npm run build
```

涉及分拣本地工作进度时，从 `frontend/` 运行 `node scripts/check-triage-work.mjs`，核对固定范围、恢复、外部修改、删除记录及存储损坏/不可用边界。该脚本不连接数据库，不能替代实际页面的连续保存、失败恢复和多视角检查。

收尾（仓库根）：

```powershell
git diff --check
git diff --stat
git status --short --branch
```

命令因权限受限失败时，保存原始错误、说明受限检查，按当前环境允许的方式重试；不要把环境失败描述为功能通过。

## 文档更新与交接

- 用户行为变化：在 changelog 顶部用当前日期描述结果；在验收清单顶部给出具体步骤和通过标准；有任务状态/优先级变化时同步 TODO。
- 文档/规则变化：修改直接负责该内容的文件及入口链接。`AGENTS.md` 存规则，本页存执行方法，TODO 存剩余工作，不互相复制。
- 不覆盖历史验证记录或旧发布说明。新源码、新便携包和正式发布分别记录对应提交、能力与证据。
- 自审最终 diff：是否达到用户目标，是否引入多余入口/依赖，是否保留安全和历史边界；检查新建文件，`git diff` 不包含未跟踪文件。
- 默认不提交、不推送。交接写明改动、验证命令及结果、未运行事项、遗留限制；若启动服务，附实际 URL、PID 或停止方式。

数据库升级/恢复按 [迁移维护说明](database-migrations.md) 和 [试用指南](industrial-trial-guide.md) 执行；不使用本页测试命令操作实际数据库。便携包构建与同包验收见 [Windows 构建说明](../packaging/windows/README.md)。
