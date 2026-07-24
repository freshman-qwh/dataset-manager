import type { AnnotationProgress, ReviewStatus } from "../types/dataset";

export const uiCopy = {
  datasetQuality: "数据质量",
  datasetQualityWorkspace: "数据质量工作台",
  reviewStatus: "审核状态",
  annotationProgress: "标注进度",
  exportCheck: "导出检查",
  sampleTags: "样本标签",
  annotationClasses: "对象类别",
  noSampleTags: "无标签",
  confirmedNoTarget: "已完成 · 无目标",
  noTargetImage: "无目标图片"
} as const;

export const annotationProgressCopy: Record<AnnotationProgress, string> = {
  not_started: "未开始",
  in_progress: "处理中",
  completed_empty: uiCopy.confirmedNoTarget,
  completed_with_objects: "已完成 · 有对象"
};

export const reviewStatusCopy: Record<ReviewStatus, string> = {
  not_reviewed: "未审核",
  in_review: "待审核",
  approved: "已通过",
  rejected: "已拒绝"
};
