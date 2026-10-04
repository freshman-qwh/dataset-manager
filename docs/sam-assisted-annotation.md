# SAM 辅助分割

在实例分割数据集的标注页，使用工具栏“SAM 辅助分割”生成待确认轮廓，然后人工精修并保存。

## 使用流程

1. 打开实例分割数据集 → 标注 → **SAM 辅助分割**（星光图标）。自定义工具栏可在配置中添加此工具。
2. 选择“包含点”点击目标，或选择“框选目标”拖框。框选会重新开始当前提示；点选可持续追加。
3. 切到“排除点”点击误选区域，也可右键添加排除点。用“撤回提示点”撤回最近一点；“重新开始”清空本轮预览。
4. 检查虚线轮廓，点击“确认轮廓并精修”（或 Enter）。轮廓作为当前类别的新多边形加入对象列表，并切换到选择工具。
5. 拖动顶点精修，支持撤销／重做；最后点击“保存草稿”或“仅完成当前”。确认轮廓只是加入当前编辑内容，不代表已经保存或完成标注。

生成中和未确认的轮廓不会写入数据库、不会修改原图，也不会把图片标记为已完成。切图、换工具、退出时沿用草稿和未保存修改保护。取消后迟到的请求结果会被丢弃。

## 模型与安装

采用 Meta 原版 SAM 的 **ViT-B**：经典 SAM 官方三种骨干中最小的一种（不是 MobileSAM）。权重 375,042,383 字节，约 357.7 MiB。代码与模型遵循 Apache-2.0。

- 官方仓库：https://github.com/facebookresearch/segment-anything
- 固定代码版本：`dca509fe793f601edb92606367a655c15ac00fdf`
- 官方权重：https://dl.fbaipublicfiles.com/segment_anything/sam_vit_b_01ec64.pth
- SHA-256：`ec2df62732614e57411cdcf32a23ffdf28910380d03139ee0f4fcbe91eb8c912`

SAM 是可选依赖，普通手工标注无需安装。下面的命令在项目 `backend/` 下运行，先选择 GPU 或 CPU 运行库之一。已安装匹配 PyTorch 的环境可跳过第一步。

```powershell
# NVIDIA GPU（本次 RTX 5050 验证使用此组合）
uv pip install --python .venv/Scripts/python.exe torch==2.10.0 torchvision==0.25.0 --index-url https://download.pytorch.org/whl/cu128

# 或：只使用 CPU，下载体积较小
uv pip install --python .venv/Scripts/python.exe torch==2.10.0 torchvision==0.25.0 --index-url https://download.pytorch.org/whl/cpu

# 安装 SAM 及轮廓处理组件；保留已安装的匹配 PyTorch
uv pip install --python .venv/Scripts/python.exe '.[sam]'

# 下载并验证权重；已有正确文件会直接校验通过
.venv/Scripts/python.exe scripts/download_sam.py
```

下载脚本从 Meta 官方站点读取，先写 `.part`，通过大小和 SHA-256 校验后再发布最终文件。已有但校验失败的文件不会自动覆盖。支持 `--output <权重完整路径>`；更改位置时同时配置 `SAM_CHECKPOINT`。

默认权重位置是当前 `STORAGE_ROOT/models/sam/sam_vit_b_01ec64.pth`。可在项目 `.env` 中设置：

```dotenv
# 可选：模型完整路径（建议绝对路径）
# SAM_CHECKPOINT=D:/models/sam_vit_b_01ec64.pth
SAM_DEVICE=auto
```

`auto` 优先使用可用 CUDA，否则用 CPU；也可显式设为 `cpu` 或 `cuda`。改变配置后重启后端。初次请求加载模型、编码图片，后续同图修正复用特征；切换图片会替换单张缓存。同一进程只处理一个 SAM 推理请求，忙碌时返回可重试提示。取消前端请求会丢弃结果，已在运行的本地计算可能仍需结束后才能重试。

若官方下载出现代理握手失败，应检查本机代理配置；无需关闭证书验证。基础 Windows 便携包不自动包含这些大体积依赖和权重，本轮交付为源代码与本机可运行环境，未重新生成 Windows ZIP。

## 边界与接口

- 支持正常图片样本；界面入口只在支持多边形的实例分割任务中提供。
- 单次最多 64 个正负点；无框时至少需要一个包含点。框必须有正面积，所有坐标按原图像素校验。
- 返回可编辑多边形，每条最多 256 个顶点。保留不相连区域为多个对象；微小无效区域会给出忽略提示。
- 当前标注格式不支持内部孔洞，SAM 掩码有孔洞时会显式提示“轮廓会填充孔洞”，需人工检查。超过 32 个有效区域时要求收紧提示。
- 单张图片上限 4000 万像素；尺寸改变、读取失败、模型缺失、推理异常都有可理解的错误提示。
- SAM 得分是模型估计值，不能替代人工验收；细小缺陷、低对比度目标仍可能需要多边形手工修正。
- `GET /api/sam/status`：检查可选依赖和权重是否就绪，不提前加载模型。
- `POST /api/samples/{id}/sam/predict`：输入 `image_width`、`image_height`、`points: [{x,y,label:0|1}]`、可选 `box:[x1,y1,x2,y2]`；只返回轮廓、模型估计分数、耗时、设备及提示。
- 确认后的对象沿用已有保存/导出接口，`source=sam_vit_b`；`attributes` 记录 `sam_model` 与 `sam_predicted_iou`，人工修改继续使用相同对象。

## 本次验收（2026-10-04）

- 本地 NVIDIA RTX 5050，PyTorch `2.10.0+cu128`，TorchVision `0.25.0+cu128`；官方 truck 示例图（1800×1200）首次加载+点选约 7.1 秒，复用特征后框选和正负点修正各约 9 毫秒。这是本机单次接口测量，不是跨机器性能保证。
- CPU 真实权重在 640×480 验收图框选成功，首次加载+编码+预测约 21.1 秒。
- 后端完整回归、前端构建、浏览器点/框/正负点/撤回/草稿保护/撤销重做/顶点修改/保存重载均见 `ACCEPTANCE_TESTS.md` 的本轮记录。
