from collections.abc import Callable
from dataclasses import dataclass
from io import BytesIO
import json
import math
from pathlib import Path, PurePosixPath
import re
from typing import BinaryIO
from xml.etree import ElementTree
from zipfile import ZIP_DEFLATED, ZipFile

from sqlmodel import Session

from app.models.sample import Sample
from app.schemas.annotation import AnnotationRead
from app.schemas.annotation_export import (
    AnnotationClassMapItem,
    AnnotationExportFormat,
    AnnotationExportPrecheckRequest,
    AnnotationExportPrecheckResponse,
    AnnotationExportSampleQuery,
)
from app.services import annotation_export_precheck_service, annotation_service, dataset_service, sample_service
from app.services.annotation_geometry import (
    BBox,
    bbox_area,
    bbox_to_coco_xywh,
    bbox_to_yolo_xywh,
    polygon_area,
    polygon_to_bbox,
    polygon_to_yolo_segment,
    rectangle_to_bbox,
    rectangle_to_polygon,
)
from app.utils.image_size import read_image_size


DETECTION_FORMATS = {"coco_detection", "yolo_detection", "voc"}
SEGMENTATION_FORMATS = {"coco_segmentation", "yolo_segmentation"}
SAFE_SPLIT_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")


@dataclass(frozen=True)
class AnnotationExportArtifact:
    content: bytes
    media_type: str
    filename: str
    precheck: AnnotationExportPrecheckResponse


@dataclass(frozen=True)
class AnnotationExportFileArtifact:
    path: Path
    media_type: str
    filename: str
    precheck: AnnotationExportPrecheckResponse
    report: dict[str, object]


@dataclass(frozen=True)
class AnnotationExportArtifactSpec:
    filename: str
    media_type: str


class AnnotationExportBlockedError(Exception):
    def __init__(self, precheck: AnnotationExportPrecheckResponse) -> None:
        super().__init__("Annotation export was blocked by precheck errors.")
        self.precheck = precheck


@dataclass(frozen=True)
class _ExportSample:
    sample: Sample
    annotations: list[AnnotationRead]
    image_width: int
    image_height: int


@dataclass(frozen=True)
class _PreparedExport:
    dataset_name: str
    precheck: AnnotationExportPrecheckResponse
    export_samples: list[_ExportSample]
    report: dict[str, object]


def export_annotations(
    session: Session,
    dataset_id: int,
    export_format: AnnotationExportFormat,
    *,
    search: str | None = None,
    file_type: str | None = None,
    file_status: str | None = None,
    tag: str | None = None,
    split: str | None = None,
    review_status: str | None = None,
    sample_ids: list[int] | None = None,
    include_empty: bool = False,
    sort_by: str = "relative_path",
    sort_order: str = "asc",
) -> AnnotationExportArtifact:
    query = AnnotationExportSampleQuery(
        search=search,
        file_type=file_type,
        file_status=file_status,
        tag=tag,
        split=split,
        review_status=review_status,
        sample_ids=sample_ids,
        sort_by=sort_by,
        sort_order="asc" if sort_order.lower() == "asc" else "desc",
    )
    prepared = _prepare_export(
        session,
        dataset_id,
        export_format,
        query=query,
        include_empty=include_empty,
    )
    precheck = prepared.precheck
    export_samples = prepared.export_samples
    report = prepared.report

    if export_format == "labelme":
        content = _export_labelme_zip(session, export_samples, report)
        return AnnotationExportArtifact(
            content=content,
            media_type="application/zip",
            filename=f"dataset-{dataset_id}-labelme-annotations.zip",
            precheck=precheck,
        )
    if export_format in {"coco_detection", "coco_segmentation"}:
        payload = _build_coco_payload(
            prepared.dataset_name,
            export_format,
            export_samples,
            precheck.class_map,
            report,
        )
        suffix = "detection" if export_format == "coco_detection" else "segmentation"
        return AnnotationExportArtifact(
            content=_json_bytes(payload),
            media_type="application/json;charset=utf-8",
            filename=f"dataset-{dataset_id}-coco-{suffix}.json",
            precheck=precheck,
        )
    if export_format in {"yolo_detection", "yolo_segmentation"}:
        content = _export_yolo_zip(export_format, export_samples, precheck.class_map, report)
        suffix = "detection" if export_format == "yolo_detection" else "segmentation"
        return AnnotationExportArtifact(
            content=content,
            media_type="application/zip",
            filename=f"dataset-{dataset_id}-yolo-{suffix}.zip",
            precheck=precheck,
        )
    content = _export_voc_zip(prepared.dataset_name, export_samples, report)
    return AnnotationExportArtifact(
        content=content,
        media_type="application/zip",
        filename=f"dataset-{dataset_id}-pascal-voc.zip",
        precheck=precheck,
    )


def export_labelme_annotations_to_path(
    session: Session,
    dataset_id: int,
    destination: Path,
    *,
    query: AnnotationExportSampleQuery,
    include_empty: bool,
    checkpoint: Callable[[], None] | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> AnnotationExportFileArtifact:
    return export_annotations_to_path(
        session,
        dataset_id,
        "labelme",
        destination,
        query=query,
        include_empty=include_empty,
        checkpoint=checkpoint,
        progress=progress,
    )


def export_annotations_to_path(
    session: Session,
    dataset_id: int,
    export_format: AnnotationExportFormat,
    destination: Path,
    *,
    query: AnnotationExportSampleQuery,
    include_empty: bool,
    checkpoint: Callable[[], None] | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> AnnotationExportFileArtifact:
    spec = annotation_export_artifact_spec(dataset_id, export_format)
    prepared = _prepare_export(
        session,
        dataset_id,
        export_format,
        query=query,
        include_empty=include_empty,
        checkpoint=checkpoint,
    )
    if export_format == "labelme":
        _write_labelme_zip(
            session,
            prepared.export_samples,
            prepared.report,
            destination,
            checkpoint=checkpoint,
            progress=progress,
        )
    else:
        payload = _build_coco_payload(
            prepared.dataset_name,
            export_format,
            prepared.export_samples,
            prepared.precheck.class_map,
            prepared.report,
            checkpoint=checkpoint,
            progress=progress,
        )
        _write_json_file(payload, destination, checkpoint=checkpoint)
    return AnnotationExportFileArtifact(
        path=destination,
        media_type=spec.media_type,
        filename=spec.filename,
        precheck=prepared.precheck,
        report=prepared.report,
    )


def annotation_export_artifact_spec(
    dataset_id: int,
    export_format: AnnotationExportFormat,
) -> AnnotationExportArtifactSpec:
    if export_format == "labelme":
        return AnnotationExportArtifactSpec(
            filename=f"dataset-{dataset_id}-labelme-annotations.zip",
            media_type="application/zip",
        )
    if export_format == "coco_detection":
        return AnnotationExportArtifactSpec(
            filename=f"dataset-{dataset_id}-coco-detection.json",
            media_type="application/json;charset=utf-8",
        )
    if export_format == "coco_segmentation":
        return AnnotationExportArtifactSpec(
            filename=f"dataset-{dataset_id}-coco-segmentation.json",
            media_type="application/json;charset=utf-8",
        )
    raise ValueError(f"Annotation export jobs do not support format: {export_format}")


def _prepare_export(
    session: Session,
    dataset_id: int,
    export_format: AnnotationExportFormat,
    *,
    query: AnnotationExportSampleQuery,
    include_empty: bool,
    checkpoint: Callable[[], None] | None = None,
) -> _PreparedExport:
    precheck = annotation_export_precheck_service.precheck_annotation_export(
        session,
        dataset_id,
        AnnotationExportPrecheckRequest(
            format=export_format,
            sample_query=query,
            include_empty=include_empty,
        ),
    )
    if precheck.blocked:
        raise AnnotationExportBlockedError(precheck)
    if checkpoint is not None:
        checkpoint()

    dataset = dataset_service.get_dataset_or_404(session, dataset_id)
    samples = sample_service.get_filtered_samples(
        session,
        dataset_id,
        search=query.search,
        file_type="image",
        file_status=query.file_status,
        tag=query.tag,
        split=query.split,
        review_status=query.review_status,
        sample_ids=query.sample_ids,
        sort_by=query.sort_by,
        sort_order=query.sort_order,
    )
    annotations_by_sample = annotation_service.annotations_by_sample(
        session,
        [sample.id for sample in samples if sample.id is not None],
    )
    if checkpoint is not None:
        checkpoint()
    export_samples, skipped_empty_count = _prepare_export_samples(
        samples,
        annotations_by_sample,
        export_format,
        include_empty,
    )
    report = _build_report(
        dataset_id,
        dataset.name,
        export_format,
        precheck,
        export_samples,
        skipped_empty_count,
        include_empty,
    )
    return _PreparedExport(
        dataset_name=dataset.name,
        precheck=precheck,
        export_samples=export_samples,
        report=report,
    )


def export_labelme_zip(
    session: Session,
    dataset_id: int,
    *,
    search: str | None = None,
    file_status: str | None = None,
    tag: str | None = None,
    split: str | None = None,
    review_status: str | None = None,
    sample_ids: list[int] | None = None,
    include_empty: bool = False,
) -> bytes:
    return export_annotations(
        session,
        dataset_id,
        "labelme",
        search=search,
        file_status=file_status,
        tag=tag,
        split=split,
        review_status=review_status,
        sample_ids=sample_ids,
        include_empty=include_empty,
    ).content


def _prepare_export_samples(
    samples: list[Sample],
    annotations_by_sample: dict[int, list[AnnotationRead]],
    export_format: AnnotationExportFormat,
    include_empty: bool,
) -> tuple[list[_ExportSample], int]:
    result: list[_ExportSample] = []
    skipped_empty_count = 0
    for sample in samples:
        annotations = [
            annotation
            for annotation in annotations_by_sample.get(sample.id or 0, [])
            if _shape_is_compatible(export_format, annotation.shape_type)
        ]
        if not annotations and not include_empty:
            skipped_empty_count += 1
            continue
        size = read_image_size(Path(sample.absolute_path))
        if size is None:
            continue
        result.append(
            _ExportSample(
                sample=sample,
                annotations=annotations,
                image_width=size[0],
                image_height=size[1],
            )
        )
    return result, skipped_empty_count


def _shape_is_compatible(export_format: AnnotationExportFormat, shape_type: str) -> bool:
    if export_format == "labelme":
        return shape_type in {"rectangle", "polygon", "point", "points"}
    if export_format in DETECTION_FORMATS | SEGMENTATION_FORMATS:
        return shape_type in {"rectangle", "polygon"}
    return False


def _build_report(
    dataset_id: int,
    dataset_name: str,
    export_format: AnnotationExportFormat,
    precheck: AnnotationExportPrecheckResponse,
    export_samples: list[_ExportSample],
    skipped_empty_count: int,
    include_empty: bool,
) -> dict[str, object]:
    report = {
        "dataset_id": dataset_id,
        "dataset_name": dataset_name,
        "format": export_format,
        "sample_count": precheck.sample_count,
        "exported_sample_count": len(export_samples),
        "exported_object_count": sum(len(item.annotations) for item in export_samples),
        "skipped_object_count": precheck.skipped_object_count,
        "skipped_empty_sample_count": skipped_empty_count,
        "include_empty": include_empty,
        "raw_images_included": False,
        "class_map": [item.model_dump(mode="json") for item in precheck.class_map],
        "error_count": precheck.error_count,
        "warning_count": precheck.warning_count,
        "info_count": precheck.info_count,
        "issues": [item.model_dump(mode="json") for item in precheck.issues],
    }
    if export_format == "labelme":
        report["exported_files"] = len(export_samples)
        report["skipped_empty_samples"] = skipped_empty_count
    return report


def _export_labelme_zip(
    session: Session,
    export_samples: list[_ExportSample],
    report: dict[str, object],
) -> bytes:
    buffer = BytesIO()
    _write_labelme_zip(session, export_samples, report, buffer)
    return buffer.getvalue()


def _write_labelme_zip(
    session: Session,
    export_samples: list[_ExportSample],
    report: dict[str, object],
    destination: Path | BinaryIO,
    *,
    checkpoint: Callable[[], None] | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> None:
    total = len(export_samples)
    with ZipFile(destination, mode="w", compression=ZIP_DEFLATED) as archive:
        for index, item in enumerate(export_samples, start=1):
            if checkpoint is not None and (index == 1 or index % 25 == 0):
                checkpoint()
            payload = annotation_service.export_labelme_annotation(session, item.sample.id or 0)
            archive.writestr(
                str(PurePosixPath("annotations") / _safe_relative_path(item.sample.relative_path).with_suffix(".json")),
                _json_bytes(payload),
            )
            if progress is not None and (index == total or index % 25 == 0):
                progress(index, total)
        if checkpoint is not None:
            checkpoint()
        archive.writestr("export_report.json", _json_bytes(report))


def _build_coco_payload(
    dataset_name: str,
    export_format: AnnotationExportFormat,
    export_samples: list[_ExportSample],
    class_map: list[AnnotationClassMapItem],
    report: dict[str, object],
    *,
    checkpoint: Callable[[], None] | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> dict[str, object]:
    category_ids = {item.name: item.coco_id for item in class_map}
    images: list[dict[str, object]] = []
    annotations: list[dict[str, object]] = []
    annotation_id = 1
    total = len(export_samples)
    for image_id, item in enumerate(export_samples, start=1):
        if checkpoint is not None and (image_id == 1 or image_id % 25 == 0):
            checkpoint()
        images.append(
            {
                "id": image_id,
                "file_name": str(_safe_relative_path(item.sample.relative_path)),
                "width": item.image_width,
                "height": item.image_height,
            }
        )
        for annotation in item.annotations:
            bbox = _annotation_bbox(annotation)
            if export_format == "coco_segmentation":
                polygon = annotation.points if annotation.shape_type == "polygon" else rectangle_to_polygon(annotation.points)
                segmentation = [[float(value) for value in polygon]]
                area = polygon_area(polygon)
            else:
                segmentation = []
                area = bbox_area(bbox)
            coco_annotation: dict[str, object] = {
                "id": annotation_id,
                "image_id": image_id,
                "category_id": category_ids[annotation.label.strip()],
                "bbox": bbox_to_coco_xywh(bbox),
                "area": area,
                "segmentation": segmentation,
                "iscrowd": 0,
            }
            standard_attributes = _standard_attributes(annotation)
            if standard_attributes:
                coco_annotation["attributes"] = standard_attributes
            annotations.append(coco_annotation)
            annotation_id += 1
        if progress is not None and (image_id == total or image_id % 25 == 0):
            progress(image_id, total)
    if checkpoint is not None:
        checkpoint()
    return {
        "info": {"description": dataset_name, "version": "dataset-manager"},
        "licenses": [],
        "images": images,
        "annotations": annotations,
        "categories": [
            {"id": item.coco_id, "name": item.name, "supercategory": "object"}
            for item in class_map
        ],
        "dataset_manager": report,
    }


def _write_json_file(
    payload: dict[str, object],
    destination: Path,
    *,
    checkpoint: Callable[[], None] | None = None,
) -> None:
    encoder = json.JSONEncoder(ensure_ascii=False, indent=2)
    buffer = bytearray()
    with destination.open("wb") as stream:
        for chunk in encoder.iterencode(payload):
            buffer.extend(chunk.encode("utf-8"))
            if len(buffer) >= 1024 * 1024:
                stream.write(buffer)
                buffer.clear()
                if checkpoint is not None:
                    checkpoint()
        buffer.extend(b"\n")
        stream.write(buffer)
    if checkpoint is not None:
        checkpoint()


def _export_yolo_zip(
    export_format: AnnotationExportFormat,
    export_samples: list[_ExportSample],
    class_map: list[AnnotationClassMapItem],
    report: dict[str, object],
) -> bytes:
    class_ids = {item.name: item.yolo_id for item in class_map}
    buffer = BytesIO()
    with ZipFile(buffer, mode="w", compression=ZIP_DEFLATED) as archive:
        for item in export_samples:
            lines: list[str] = []
            for annotation in item.annotations:
                class_id = class_ids[annotation.label.strip()]
                if export_format == "yolo_detection":
                    values = bbox_to_yolo_xywh(
                        _annotation_bbox(annotation),
                        item.image_width,
                        item.image_height,
                    )
                else:
                    polygon = annotation.points if annotation.shape_type == "polygon" else rectangle_to_polygon(annotation.points)
                    values = polygon_to_yolo_segment(polygon, item.image_width, item.image_height)
                lines.append(" ".join([str(class_id), *(_format_yolo(value) for value in values)]))
            split_name = _safe_split(item.sample.split)
            label_path = PurePosixPath("labels") / split_name / _safe_relative_path(item.sample.relative_path).with_suffix(".txt")
            archive.writestr(str(label_path), ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8"))
        archive.writestr("data.yaml", _yolo_data_yaml(export_format, class_map).encode("utf-8"))
        archive.writestr("classes.txt", ("\n".join(item.name for item in class_map) + "\n").encode("utf-8"))
        archive.writestr("export_report.json", _json_bytes(report))
    return buffer.getvalue()


def _yolo_data_yaml(export_format: AnnotationExportFormat, class_map: list[AnnotationClassMapItem]) -> str:
    task = "detect" if export_format == "yolo_detection" else "segment"
    lines = [
        "path: .",
        "train: images/train",
        "val: images/val",
        "test: images/test",
        f"task: {task}",
        "names:",
    ]
    lines.extend(f"  {item.yolo_id}: {_yaml_scalar(item.name)}" for item in class_map)
    return "\n".join(lines) + "\n"


def _export_voc_zip(
    dataset_name: str,
    export_samples: list[_ExportSample],
    report: dict[str, object],
) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, mode="w", compression=ZIP_DEFLATED) as archive:
        for item in export_samples:
            relative_path = _safe_relative_path(item.sample.relative_path)
            root = ElementTree.Element("annotation")
            ElementTree.SubElement(root, "folder").text = dataset_name
            ElementTree.SubElement(root, "filename").text = item.sample.filename
            ElementTree.SubElement(root, "path").text = str(relative_path)
            size = ElementTree.SubElement(root, "size")
            ElementTree.SubElement(size, "width").text = str(item.image_width)
            ElementTree.SubElement(size, "height").text = str(item.image_height)
            ElementTree.SubElement(size, "depth").text = "3"
            for annotation in item.annotations:
                bbox = _annotation_bbox(annotation)
                node = ElementTree.SubElement(root, "object")
                ElementTree.SubElement(node, "name").text = annotation.label.strip()
                ElementTree.SubElement(node, "pose").text = "Unspecified"
                standard_attributes = _standard_attributes(annotation)
                ElementTree.SubElement(node, "occluded").text = _xml_bool(standard_attributes.get("occluded", False))
                ElementTree.SubElement(node, "truncated").text = _xml_bool(standard_attributes.get("truncated", False))
                ElementTree.SubElement(node, "difficult").text = _xml_bool(standard_attributes.get("difficult", False))
                box = ElementTree.SubElement(node, "bndbox")
                ElementTree.SubElement(box, "xmin").text = str(math.floor(bbox.x_min))
                ElementTree.SubElement(box, "ymin").text = str(math.floor(bbox.y_min))
                ElementTree.SubElement(box, "xmax").text = str(math.ceil(bbox.x_max))
                ElementTree.SubElement(box, "ymax").text = str(math.ceil(bbox.y_max))
            xml = ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)
            archive.writestr(str(PurePosixPath("annotations") / relative_path.with_suffix(".xml")), xml)
        archive.writestr("export_report.json", _json_bytes(report))
    return buffer.getvalue()


def _annotation_bbox(annotation: AnnotationRead) -> BBox:
    if annotation.shape_type == "rectangle":
        return rectangle_to_bbox(annotation.points)
    return polygon_to_bbox(annotation.points)


def _standard_attributes(annotation: AnnotationRead) -> dict[str, bool]:
    return {
        key: bool(annotation.attributes[key])
        for key in ("occluded", "truncated", "difficult")
        if key in annotation.attributes
    }


def _xml_bool(value: object) -> str:
    return "1" if bool(value) else "0"


def _safe_relative_path(value: str) -> PurePosixPath:
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} or ":" in part for part in path.parts):
        raise ValueError(f"Unsafe sample relative path: {value}")
    return path


def _safe_split(value: str | None) -> str:
    normalized = (value or "unassigned").strip()
    return normalized if SAFE_SPLIT_PATTERN.fullmatch(normalized) else "unassigned"


def _format_yolo(value: float) -> str:
    return f"{value:.6f}"


def _yaml_scalar(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_. -]+", value) and value == value.strip():
        return value
    return json.dumps(value, ensure_ascii=False)


def _json_bytes(payload: dict[str, object]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
