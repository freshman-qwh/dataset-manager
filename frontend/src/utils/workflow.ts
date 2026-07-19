import type { AnnotationProgress, DatasetTaskType, ReviewStatus } from "../types/dataset";

export const datasetTaskOptions: Array<{ value: DatasetTaskType; label: string; description: string }> = [
  { value: "detection", label: "目标检测", description: "使用矩形框标记目标，默认导出 COCO detection。" },
  { value: "segmentation", label: "多边形分割", description: "使用多边形勾勒目标，默认导出 COCO segmentation。" },
  { value: "classification", label: "分类整理", description: "使用样本标签整理类别，不提供几何绘制工具。" }
];

export const annotationProgressCopy: Record<AnnotationProgress, string> = {
  not_started: "未开始",
  in_progress: "处理中",
  completed_empty: "已完成 · 无目标",
  completed_with_objects: "已完成 · 有对象"
};

export const reviewStatusCopy: Record<ReviewStatus, string> = {
  not_reviewed: "未审核",
  in_review: "待审核",
  approved: "已通过",
  rejected: "已拒绝"
};
