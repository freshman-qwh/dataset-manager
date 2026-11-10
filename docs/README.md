# 文档导航

本页按“使用 → 开发 → 契约 → 历史证据”组织。当前实现和本轮检查优先；日期记录只说明当时状态。当前源码已包含后续快速验证，2026-10-30 的便携包不包含该页面，不能混用能力声明。

## 使用产品

| 要完成的事 | 阅读入口 |
| --- | --- |
| 了解定位、核心流程与功能取舍 | [产品范围](product-scope.md)、[项目首页](../README.md) |
| 快速切换分散的数据集、浏览嵌套目录和图片 | [本地浏览](local-browsing.md) |
| 管理项目、对象类别与批次，导入 MVTec / VisA | [项目、类别与批次](project-category-batch.md) |
| 复用导入格式和类别/工件规则，接收下一采集批次 | [新批次接收方案](project-category-batch.md#新批次接收方案) |
| 继续上次浏览、生成数据集名片、查看正常与缺陷对照 | [日常浏览与对照](daily-tools.md) |
| 续接分拣范围与进度、查看同工件多视角 | [分拣续接](daily-tools.md#续接分拣工作)、[工件多视角](daily-tools.md#查看同工件多视角) |
| 浏览公开工业异常检测数据、官方预览与获取入口 | [数据集图书馆](anomaly-dataset-library.md) |
| 整理工业图片，生成独立训练/验证/测试数据包 | [工业试用指南](industrial-trial-guide.md) |
| 按训练包、独立评估或正常探索检查阻断和覆盖缺口 | [交付目标验收清单](industrial-trial-guide.md#按交付目标核对验收清单) |
| 建立本地基线、复核误报漏检、验证第二批 | [快速验证指南](quick-validation-guide.md) |
| 使用本地 SAM 进行几何标注 | [SAM 辅助标注](sam-assisted-annotation.md) |
| 执行人工验收 | [验收清单](../ACCEPTANCE_TESTS.md) |

## 参与开发

| 要查的内容 | 负责文档 |
| --- | --- |
| 共同约束与目录分工 | [根 AGENTS](../AGENTS.md)、[后端规则](../backend/AGENTS.md)、[前端规则](../frontend/AGENTS.md)、[文档规则](AGENTS.md) |
| 安装、启动、验证、文档更新与交接 | [开发工作流](development-workflow.md) |
| 当前优先级、未完成工作 | [TODO](../TODO.md) |
| 已交付变化 | [CHANGELOG](../CHANGELOG.md) |
| 按任务选技能与插件限制 | [技能指南](codex-skill-plugin-usage.md) |
| 数据库维护与便携包构建 | [迁移与备份](database-migrations.md)、[Windows 构建](../packaging/windows/README.md) |

## 设计契约

读到历史阶段计划时，以当前 TODO 及实际实现判断是否已交付；以下链接用于定位对应语义。

- 分拣与导出：[快速分拣/目录导出](quick-sorting-directory-export.md)、[批量分拣](batch-triage.md)、[旧目录映射](triage-directory-mapping.md)、[界面术语](ui-copy-glossary.md)。
- 几何标注：[接口集成](annotation-interface-integration.md)、[导入格式](annotation-import-formats.md)、[导出契约](annotation-format-export-contract.md)。
- 历史与复用：[revision](dataset-revision-contract.md)、[快照](dataset-snapshot-contract.md)、[保存视图](dataset-saved-view-contract.md)、[精确重复与泄漏](exact-duplicate-leakage-contract.md)。
- 工业主线：[工业实施计划（2026-10-29）](industrial-anomaly-release-plan-2026-10-29.md)、[快速验证实施计划（2026-10-30）](quick-validation-plan-2026-10-30.md)。

## 历史计划与验证记录

- [快速验证本机记录（2026-11-01）](quick-validation-verification-2026-11-01.md)：真实基线/ROI/复核/恢复的工程证据及未完成外部验收。
- [工业便携交付记录（2026-10-30）](industrial-trial-delivery-2026-10-30.md)：对应 ZIP、源码、hash 与当时验证范围。
- [验收审视（2026-10-29）](acceptance-review-2026-10-29.md)、[早期产品与架构审视](product-architecture-ux-performance-review.md)、[分拣体验收敛计划](quick-triage-ux-convergence.md)、[旧后续路线](post-ux-d-roadmap.md)。
- [v0.4.1 TODO 归档](todo-v0.4.1-archive.md) 与 `releases/`：历史背景，不作为当前新增范围或发布状态的来源。

新增或调整文档时遵守 [文档规则](AGENTS.md)，更新本页对应入口。无需把相同状态逐页复制。
