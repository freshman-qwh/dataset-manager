import type { DatasetTaskType } from "../types/dataset";

export { annotationProgressCopy, reviewStatusCopy } from "./uiCopy";

export const datasetTaskOptions: Array<{ value: DatasetTaskType; label: string; description: string }> = [
  { value: "detection", label: "目标检测", description: "使用矩形框标记目标，默认导出 COCO detection。" },
  { value: "segmentation", label: "实例分割", description: "使用多边形或画笔勾勒每个目标实例，默认导出 COCO segmentation。" },
  { value: "classification", label: "分类整理", description: "使用样本标签整理类别，不提供几何绘制工具。" }
];
