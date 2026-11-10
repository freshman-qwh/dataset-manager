# 导入样本元数据

用本地 CSV 或 JSON 为已登记的样本补充标签、训练划分、备注和自定义属性。样本仍保留原始文件的位置和内容。

1. 在数据集详情页通过“添加图片”扫描目录，登记需要更新的样本。
2. 打开“管理与导出 → 其他操作 → 导入元数据”，填写后端可读取的 CSV 或 JSON 文件绝对路径，再选择匹配字段和标签列。
3. 点击“预览导入”，核对预计更新的行数、跳过项和错误。确认后才创建导入任务。已写入的变更可从任务中心显式回滚。

## 文件示例

CSV 表头需包含所选的匹配字段。下例按 `relative_path` 匹配，标签列使用 `tags`，多个标签用分号分隔。

```csv
relative_path,tags,split,notes,quality
images/a.png,"cat;review",train,"good sample",high
```

JSON 接受样本对象数组，也可以用 `samples` 包裹数组。

```json
{
  "samples": [
    {
      "relative_path": "images/a.png",
      "tags": ["cat", "review"],
      "split": "train",
      "notes": "good sample",
      "quality": "high"
    }
  ]
}
```

## 如何匹配

- 可选 `sample_id`、`relative_path`、`absolute_path`、`filename` 或 `file_hash`。同一匹配值对应多个样本时，该行会报错。
- `relative_path` 以数据集扫描目录为起点。Windows 绝对路径可使用 `D:/...` 或 `D:\...`。绝对路径直接匹配失败时，如果文件位于扫描目录内，系统还会尝试按相对路径匹配。
- `tags`、`split`、`review_status` 和 `notes` 是保留字段。标签列默认是 `tags`，可在导入时另选。`quality` 等其他非匹配字段会保存为样本自定义属性。

如果导入的是检测框或分割轮廓，使用[标注导入](annotation-import-formats.md)。
