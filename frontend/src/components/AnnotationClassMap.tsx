import type { AnnotationClassMapItem, AnnotationExportFormat } from "../types/annotationExport";

interface Props {
  format: AnnotationExportFormat;
  classMap: AnnotationClassMapItem[];
}

export default function AnnotationClassMap({ format, classMap }: Props) {
  let heading = "类别名称";
  let idField: "coco_id" | "yolo_id" | null = null;
  if (format === "coco_detection" || format === "coco_segmentation") {
    heading = "COCO 类别编号（从 1 开始）";
    idField = "coco_id";
  } else if (format === "yolo_detection" || format === "yolo_segmentation") {
    heading = "YOLO 类别编号（从 0 开始）";
    idField = "yolo_id";
  }

  return (
    <>
      <h3 className="text-xs font-semibold text-gray-700">{heading}</h3>
      <div className="mt-2 flex flex-wrap gap-2">
        {classMap.map(item => (
          <span key={item.name} className="max-w-full break-words rounded-md bg-gray-100 px-2 py-1 text-xs text-gray-700">
            {idField === null ? item.name : `${item[idField]} · ${item.name}`}
          </span>
        ))}
      </div>
    </>
  );
}
