# Codex 开发技能与插件使用指南

## 目标

本项目采用“项目规则 + 项目工作流 + 按需专业技能”三层结构：

1. `AGENTS.md` 定义长期有效的仓库约束、MVP 范围、数据安全与完成标准。
2. `dataset-manager-development` 负责本项目固定的开发、验证和文档更新流程。
3. 第三方插件/技能只在任务匹配时补充专业方法，不得覆盖前两层。

安装范围是当前仓库，不是全局开发环境。打开新任务或重启 Codex 后，新增技能才会稳定进入可发现列表。

## 已安装内容

### wshobson/agents 插件

来源：<https://github.com/wshobson/agents>

审计版本：`c4b82b0ad771190355eb8e204b1329732a18449a`

| 插件 | 版本 | 本项目主要用途 | 当前限制 |
| --- | --- | --- | --- |
| `python-development` | 1.2.3 + Codex cachebuster | FastAPI/Python、pytest、错误处理、类型和异步代码 | 含打包、后台任务、可观测性等非 MVP 技能，必须按需选择 |
| `unit-testing` | 1.2.1 + Codex cachebuster | 保留上游测试 agent/command 资料 | 当前包没有 Codex `skills/`，不能作为可调用技能依赖 |
| `frontend-mobile-development` | 1.2.3 + Codex cachebuster | React 状态与 Tailwind 设计系统 | Next.js、React Native 不适用于当前 Vite Web 项目 |
| `ui-design` | 1.0.5 + Codex cachebuster | Web UI、响应式、无障碍、视觉和设计系统 | iOS、Android、React Native 技能默认禁用思路 |

插件文件位于 `plugins/`，项目市场清单位于 `.agents/plugins/marketplace.json`。安装器也在用户 Codex 配置中启用了对应插件项。

### obra/superpowers 单项技能

来源：<https://github.com/obra/superpowers>

审计版本：`d884ae04edebef577e82ff7c4e143debd0bbec99`

仅安装以下四项到 `.agents/skills/`，没有安装完整 Superpowers 插件、bootstrap、hooks、worktree 或全套强制流程：

- `systematic-debugging`
- `verification-before-completion`
- `requesting-code-review`
- `receiving-code-review`

## 任务路由

### 所有代码任务

始终先使用 `dataset-manager-development`，建立 Git 状态并读取相关项目文件。第三方技能的建议若与 `AGENTS.md` 冲突，以项目规则为准。

### Bug、异常和测试失败

使用 `$systematic-debugging`：

1. 复现并保存错误证据。
2. 查看近期 diff，定位故障发生在哪一层。
3. 形成单一根因假设，用最小实验验证。
4. 添加回归验证后只修根因。

若连续三次修复假设失败，停止叠加补丁，向用户说明证据并讨论架构问题。

### Python、FastAPI 与 SQLite

按任务选择插件中的单个技能：

- 测试、fixture、API 边界：`python-development:python-testing-patterns`
- 输入校验、批处理部分失败、异常映射：`python-development:python-error-handling`
- Pydantic/SQLModel 类型边界：`python-development:python-type-safety`
- FastAPI 异步 I/O：`python-development:async-python-patterns`
- 文件、连接或流清理：`python-development:python-resource-management`

不要因为插件提供了能力就引入 Celery、微服务、分布式追踪、发布 PyPI 或新的大型依赖。

### React、TypeScript 与 Tailwind

当前前端是 React 18 + TypeScript + Vite + Tailwind，不是 Next.js 或移动应用：

- 跨组件状态或服务端状态决策：`frontend-mobile-development:react-state-management`
- Tailwind 组件约束和设计 token：`frontend-mobile-development:tailwind-design-system`
- 响应式画布/侧栏/工具栏：`ui-design:responsive-design`
- 键盘操作、焦点、ARIA、对比度：`ui-design:accessibility-compliance`
- 视觉层级、间距、颜色、图标：`ui-design:visual-design-foundations`
- 可复用 React 组件 API：`ui-design:web-component-design`
- 统一组件规范：`ui-design:design-system-patterns`

`tailwind-design-system` 上游以 Tailwind v4 为主；本项目是 Tailwind v3，采用其设计方法时必须先核对语法和配置兼容性。

### 测试与验收

`unit-testing` 插件当前没有 Codex 技能目录，所以测试路由如下：

1. Python 测试使用 `python-testing-patterns`。
2. Bug 先使用 `systematic-debugging` 建立复现。
3. 后端运行相关 pytest；共享行为变更再扩大到完整后端测试。
4. 前端至少运行 `npm run build`；交互或布局变化在可行时用浏览器做真实页面验证。
5. 最终使用 `$verification-before-completion`，以本轮新鲜输出支持完成声明。

### 代码审查

重大功能完成或合并前使用 `$requesting-code-review`。上游技能默认请求 reviewer subagent，但本项目采用以下兼容策略：

- 用户明确请求独立 reviewer/subagent 时，才委派只读审查。
- 其他情况在当前任务内按 `.agents/skills/requesting-code-review/code-reviewer.md` 做只读自审。
- 审查必须对照用户需求、`TODO.md`、相关设计契约和实际 diff。
- 问题按 Critical / Important / Minor 分级，给出文件与行号，不把风格偏好夸大为阻断问题。

收到用户、GitHub 或其他 reviewer 的意见时使用 `$receiving-code-review`：先验证意见适用于当前代码和 MVP，再逐项实现；不清楚的意见先澄清。

## 完成门禁

任何“已完成、已修复、测试通过、可以合并”的表述前，必须有本轮新鲜证据：

- 代码变更：至少运行聚焦检查和 `git diff --check`。
- 后端共享逻辑：运行相关 pytest，必要时完整 pytest 与 compileall。
- 前端代码：运行 `npm run build`。
- UI/交互：构建通过之外，尽可能进行浏览器人工路径验证。
- 未运行的检查必须明确列出，不能用“应该通过”代替。

## 推荐提示词

通常不必手工点名技能，Codex 会根据描述匹配。需要强制指定时可使用：

```text
使用 $systematic-debugging 复现并定位这个标注保存失败，不要先猜修复。
```

```text
使用 python-development:python-testing-patterns 为 LabelMe 导入边界补 pytest，遵守现有 service/API 分层。
```

```text
使用 ui-design:accessibility-compliance 和 ui-design:responsive-design 审查标注工作区，只报告当前 Vite Web 页面的问题。
```

```text
使用 $requesting-code-review 对照 docs/annotation-format-export-contract.md 审查当前 diff；不委派子代理，在本任务内完成只读审查。
```

## 维护原则

- 升级前先查看上游 changelog、目标 `SKILL.md`、脚本、hooks 和许可证差异。
- 不自动跟随 `main` 更新；记录审计 commit 后再升级。
- 不安装整个 Superpowers 插件，除非用户明确接受其 brainstorming、TDD、worktree、subagent 和 branch-finishing 全套流程。
- 新增技能前先判断现有技能是否已覆盖，避免技能列表膨胀和触发冲突。
- 插件或技能变更后新开一个 Codex 任务验证发现与触发情况。

## 验证清单

安装或升级后检查：

1. `.agents/plugins/marketplace.json` 包含四个 wshobson 插件。
2. `plugins/*/.codex-plugin/plugin.json` 可解析，版本符合预期。
3. `.agents/skills/` 包含四个 Superpowers 技能且每项有 `SKILL.md`。
4. 新任务的技能列表能发现这些项目技能/插件技能。
5. 用一个 Bug、一个 Python 测试和一个 UI 审查提示分别做触发冒烟测试。
