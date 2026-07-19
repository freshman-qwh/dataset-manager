from dataclasses import dataclass
import math


@dataclass(frozen=True)
class BBox:
    x_min: float
    y_min: float
    x_max: float
    y_max: float

    @property
    def width(self) -> float:
        return self.x_max - self.x_min

    @property
    def height(self) -> float:
        return self.y_max - self.y_min


def pair_points(points: list[float]) -> list[tuple[float, float]]:
    if len(points) < 2 or len(points) % 2:
        raise ValueError("Point arrays must contain coordinate pairs.")
    paired: list[tuple[float, float]] = []
    for index in range(0, len(points), 2):
        x = float(points[index])
        y = float(points[index + 1])
        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError("Coordinates must be finite numbers.")
        paired.append((x, y))
    return paired


def rectangle_to_bbox(points: list[float]) -> BBox:
    if len(points) != 4:
        raise ValueError("Rectangle annotations require 4 coordinates.")
    xtl, ytl, xbr, ybr = [float(value) for value in points]
    if any(not math.isfinite(value) for value in (xtl, ytl, xbr, ybr)):
        raise ValueError("Rectangle coordinates must be finite numbers.")
    bbox = BBox(x_min=xtl, y_min=ytl, x_max=xbr, y_max=ybr)
    if bbox.width <= 0 or bbox.height <= 0:
        raise ValueError("Rectangle coordinates must have positive width and height.")
    return bbox


def polygon_to_bbox(points: list[float]) -> BBox:
    paired = pair_points(points)
    if len(paired) < 3:
        raise ValueError("Polygon annotations require at least 3 points.")
    xs = [point[0] for point in paired]
    ys = [point[1] for point in paired]
    bbox = BBox(x_min=min(xs), y_min=min(ys), x_max=max(xs), y_max=max(ys))
    if bbox.width <= 0 or bbox.height <= 0:
        raise ValueError("Polygon bounds must have positive width and height.")
    return bbox


def rectangle_to_polygon(points: list[float]) -> list[float]:
    bbox = rectangle_to_bbox(points)
    return [
        bbox.x_min,
        bbox.y_min,
        bbox.x_max,
        bbox.y_min,
        bbox.x_max,
        bbox.y_max,
        bbox.x_min,
        bbox.y_max,
    ]


def polygon_area(points: list[float]) -> float:
    paired = pair_points(points)
    if len(paired) < 3:
        raise ValueError("Polygon annotations require at least 3 points.")
    total = 0.0
    for index, (x1, y1) in enumerate(paired):
        x2, y2 = paired[(index + 1) % len(paired)]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def bbox_area(bbox: BBox) -> float:
    if bbox.width <= 0 or bbox.height <= 0:
        raise ValueError("BBox must have positive width and height.")
    return bbox.width * bbox.height


def bbox_to_coco_xywh(bbox: BBox) -> list[float]:
    if bbox.width <= 0 or bbox.height <= 0:
        raise ValueError("BBox must have positive width and height.")
    return [bbox.x_min, bbox.y_min, bbox.width, bbox.height]


def bbox_to_yolo_xywh(bbox: BBox, image_width: int, image_height: int) -> list[float]:
    _validate_image_size(image_width, image_height)
    if bbox.width <= 0 or bbox.height <= 0:
        raise ValueError("BBox must have positive width and height.")
    return [
        ((bbox.x_min + bbox.x_max) / 2.0) / image_width,
        ((bbox.y_min + bbox.y_max) / 2.0) / image_height,
        bbox.width / image_width,
        bbox.height / image_height,
    ]


def polygon_to_yolo_segment(points: list[float], image_width: int, image_height: int) -> list[float]:
    _validate_image_size(image_width, image_height)
    paired = pair_points(points)
    if len(paired) < 3:
        raise ValueError("Polygon annotations require at least 3 points.")
    segment: list[float] = []
    for x, y in paired:
        segment.extend([x / image_width, y / image_height])
    return segment


def points_within_image(points: list[float], image_width: int, image_height: int) -> bool:
    _validate_image_size(image_width, image_height)
    return all(0 <= x <= image_width and 0 <= y <= image_height for x, y in pair_points(points))


def _validate_image_size(image_width: int, image_height: int) -> None:
    if image_width <= 0 or image_height <= 0:
        raise ValueError("Image dimensions must be positive.")
