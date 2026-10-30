# 工业异常检测试用交付记录 · 2026-10-30

当前可交付图像级工业异常检测数据准备的试用候选。主流程为扫描、分拣、工件/批次分组、独立划分、训练包导出及读取；备份恢复路径已接通。尚未达到经过真实用户验收的正式定版。

## 候选文件与对应源码

- 分支：`codex/industrial-anomaly`，仅本地提交，未推送。
- 程序源码提交：`3d5037289afd8c745aae63831a09146257cc8869`。
- ZIP：`dist/DatasetManager-industrial-trial-20261030-windows-x64.zip`。
- 文件大小：31,613,279 字节。
- SHA-256：`9E80CB0EC6BE7BBBE500467CF0DBCB524D52CE832AF8E0A10F5CEED3595186B0`。
- 包内 `build-manifest.json` 记录源码提交、构建测试和外部验收边界；构建时没有未提交的受版本控制文件改动。
- 后续验收脚本/记录提交不改变此候选程序内容；检查程序时以包内源码提交为准。

## 分阶段提交

| 阶段 | 提交 | 结果 |
| --- | --- | --- |
| 规划 | `8625eba` | 验收问题、定位与 IA0–IA5 规则 |
| IA0 | `ea667be` | 启动、统一 OK 显示、坏图与独立读取契约 |
| IA1 | `e1ccabe` | 工业用途、概览、分拣筛选及合成示例 |
| IA2 | `bd17468` | 工件/批次预览确认、保存视图、快照 v2 |
| IA3 | `e4fab87` | 纯正常训练、传递合组、独立验证/测试及冻结计划 |
| 文档修正 | `90110f0` | 修正阶段文档中文编码 |
| IA4 | `c54a1df` | 校验后的目录/ZIP、后台任务、真实读取脚本 |
| IA5 工程 | `3d50372` | 元数据恢复、启动指引、响应丢失核对及候选构建 |

## 已验证的范围

1. 源码环境：后端 **266 项通过**；前端构建通过。剩余告警为已有兼容/依赖及构建分块提示，未作为功能通过依据。
2. 隔离便携构建环境：**257 项通过、9 项跳过**。跳过项属于可选 SAM 组件；工业图像级主流程未因此跳过。
3. 浏览器：分组预览/确认/筛选、保存视图恢复、协议预览/划分写回、真实 ZIP 下载、备份恢复和旧库维护提示。模拟判定已经提交但 PUT 响应丢失，GET 核对版本与内容后正常推进，没有重放写入。
4. 同一最终 ZIP：在中文/空格解压路径和受限 PATH 下，生成 16 张合成示例，按工件组生成协议及训练包。训练包从其他工作目录、在独立 Anomalib 2.7.0 CPU 环境完整遍历：**train=6、val=6、test=4，split_preserved=true**。逐图标签、文件 hash 和集合核对通过；没有拆分工件来凑建议比例。
5. 同一 ZIP：创建包含引用快照的元数据 ZIP，校验恢复到新工作区，再用 `--workspace` 启动恢复位置。16 张记录、快照 v2 和工件判定可读；原图 hash 保持。损坏、缺失和非法路径恢复拒绝路径有自动化覆盖。
6. 同一 ZIP 的基础回归：端口冲突、重复启动、异常退出恢复、覆盖升级、原数据保留通过。

可重复执行的工业包验收：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File packaging/windows/test-industrial-trial.ps1 -ZipPath 'dist/DatasetManager-industrial-trial-20261030-windows-x64.zip' -ReaderPython '独立读取环境的 python.exe'
```

本机证据保留在：

- `output/acceptance/工业便携验收 16161f87/acceptance-report.json`
- `output/acceptance/工业便携验收 16161f87/reader-check.log`
- `output/playwright/industrial-20261030/`
- `.tmp/industrial-build.log`
- `.tmp/industrial-portable-acceptance.log`
- `.tmp/industrial-portable-regression.log`
- `backend/.tmp/industrial-final-source.log`

## 定版前仍缺的证据

- 同一候选在独立、干净的 Windows 10/11 x64 环境完成核心链路。当前机器的隔离目录和受限 PATH 不能替代此项。
- 2–3 位工业目标用户使用各自真实的第一批和第二批数据；记录交付用时、每百张操作用时、修正/求助次数，至少两位独立复用。
- 根据上述实测再决定需要补哪些体验功能；当前没有真实用户用时或模型精度结论。

当前试用边界：图像级协议，每项目最多 10000 个登记文件；元数据备份上限 20000 文件/2 GiB。原图与历史下载包另行备份。像素级协议、预测回流与近重复检查仍在后续范围；训练框架和可选 SAM 权重没有加入基础便携包。

操作说明见 [工业试用指南](industrial-trial-guide.md)，具体回归步骤见 [人工验收清单](../ACCEPTANCE_TESTS.md)。
