import { type PointerEvent, useCallback, useEffect, useMemo, useRef, useState, type WheelEvent } from "react";

import type { AnnotationObject, AnnotationShapeType, Tag } from "../../types/dataset";
import type { AnnotationTool } from "./AnnotationToolbar";

interface Point {
  x: number;
  y: number;
}

interface Size {
  width: number;
  height: number;
}

interface Transform {
  scale: number;
  translateX: number;
  translateY: number;
}

type DragState =
  | {
      type: "pan";
      start: Point;
      originalTransform: Transform;
    }
  | {
      type: "drawing-rectangle";
      start: Point;
      previousObjects: AnnotationObject[];
    }
  | {
      type: "object";
      clientId: string;
      start: Point;
      previousObjects: AnnotationObject[];
    }
  | {
      type: "vertex";
      clientId: string;
      vertexIndex: number;
      start: Point;
      previousObjects: AnnotationObject[];
    };

interface DraftShape {
  shape_type: AnnotationShapeType;
  points: number[];
}

interface AnnotationCanvasProps {
  imageUrl: string;
  objects: AnnotationObject[];
  activeObjectId: string | null;
  tool: AnnotationTool;
  activeLabel: string;
  activeTagId: number | null;
  tags: Tag[];
  onObjectsPreview: (objects: AnnotationObject[]) => void;
  onObjectsCommit: (objects: AnnotationObject[], previousObjects?: AnnotationObject[]) => void;
  onActiveObjectChange: (clientId: string | null) => void;
  onStatusChange: (status: string) => void;
  onDeleteActive: () => void;
}

const fallbackColors = ["#2563eb", "#dc2626", "#16a34a", "#9333ea", "#ea580c", "#0891b2", "#be123c"];

function cloneObjects(objects: AnnotationObject[]): AnnotationObject[] {
  return objects.map((object) => ({ ...object, points: [...object.points] }));
}

function makeClientId(): string {
  return `local-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function distance(a: Point, b: Point): number {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

function normalizeRectangle(points: number[]): number[] {
  const [x1, y1, x2, y2] = points;
  return [Math.min(x1, x2), Math.min(y1, y2), Math.max(x1, x2), Math.max(y1, y2)];
}

function pairPoints(points: number[]): Point[] {
  const pairs: Point[] = [];
  for (let index = 0; index < points.length - 1; index += 2) {
    pairs.push({ x: points[index], y: points[index + 1] });
  }
  return pairs;
}

function polygonPoints(points: number[]): string {
  return pairPoints(points)
    .map((point) => `${point.x},${point.y}`)
    .join(" ");
}

function movePoints(points: number[], dx: number, dy: number): number[] {
  return points.map((value, index) => value + (index % 2 === 0 ? dx : dy));
}

function getObjectVertices(object: AnnotationObject): Point[] {
  if (object.shape_type === "rectangle") {
    const [xtl, ytl, xbr, ybr] = normalizeRectangle(object.points);
    return [
      { x: xtl, y: ytl },
      { x: xbr, y: ytl },
      { x: xbr, y: ybr },
      { x: xtl, y: ybr }
    ];
  }
  return pairPoints(object.points);
}

function updateVertex(object: AnnotationObject, vertexIndex: number, point: Point): AnnotationObject {
  if (object.shape_type === "rectangle") {
    const [xtl, ytl, xbr, ybr] = normalizeRectangle(object.points);
    const next = [xtl, ytl, xbr, ybr];
    if (vertexIndex === 0) {
      next[0] = point.x;
      next[1] = point.y;
    } else if (vertexIndex === 1) {
      next[2] = point.x;
      next[1] = point.y;
    } else if (vertexIndex === 2) {
      next[2] = point.x;
      next[3] = point.y;
    } else if (vertexIndex === 3) {
      next[0] = point.x;
      next[3] = point.y;
    }
    return { ...object, points: normalizeRectangle(next) };
  }
  const nextPoints = [...object.points];
  nextPoints[vertexIndex * 2] = point.x;
  nextPoints[vertexIndex * 2 + 1] = point.y;
  return { ...object, points: nextPoints };
}

function clampPoint(point: Point, imageSize: Size | null): Point {
  if (!imageSize) {
    return point;
  }
  return {
    x: Math.min(Math.max(point.x, 0), imageSize.width),
    y: Math.min(Math.max(point.y, 0), imageSize.height)
  };
}

export default function AnnotationCanvas({
  imageUrl,
  objects,
  activeObjectId,
  tool,
  activeLabel,
  activeTagId,
  tags,
  onObjectsPreview,
  onObjectsCommit,
  onActiveObjectChange,
  onStatusChange,
  onDeleteActive
}: AnnotationCanvasProps) {
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const objectsRef = useRef<AnnotationObject[]>(objects);
  const dragRef = useRef<DragState | null>(null);
  const [viewport, setViewport] = useState<Size>({ width: 0, height: 0 });
  const [imageSize, setImageSize] = useState<Size | null>(null);
  const [transform, setTransform] = useState<Transform>({ scale: 1, translateX: 0, translateY: 0 });
  const [draft, setDraft] = useState<DraftShape | null>(null);
  const [fitKey, setFitKey] = useState(0);

  useEffect(() => {
    objectsRef.current = objects;
  }, [objects]);

  useEffect(() => {
    setDraft(null);
    dragRef.current = null;
    setImageSize(null);
    setTransform({ scale: 1, translateX: 0, translateY: 0 });
    setFitKey((value) => value + 1);
  }, [imageUrl]);

  useEffect(() => {
    const wrapper = wrapperRef.current;
    if (!wrapper) {
      return;
    }
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      setViewport({ width: entry.contentRect.width, height: entry.contentRect.height });
    });
    observer.observe(wrapper);
    return () => observer.disconnect();
  }, []);

  const tagById = useMemo(() => new Map(tags.map((tag) => [tag.id, tag])), [tags]);
  const tagByName = useMemo(() => new Map(tags.map((tag) => [tag.name.toLowerCase(), tag])), [tags]);

  const fitImage = useCallback(() => {
    if (!imageSize || viewport.width <= 0 || viewport.height <= 0) {
      return;
    }
    const scale = Math.max(
      Math.min((viewport.width - 48) / imageSize.width, (viewport.height - 48) / imageSize.height),
      0.05
    );
    setTransform({
      scale,
      translateX: (viewport.width - imageSize.width * scale) / 2,
      translateY: (viewport.height - imageSize.height * scale) / 2
    });
  }, [imageSize, viewport]);

  useEffect(() => {
    fitImage();
  }, [fitImage, fitKey]);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      const target = event.target;
      if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement) {
        return;
      }
      if (event.key === "Escape") {
        setDraft(null);
        dragRef.current = null;
      } else if (event.key === "Backspace" && draft?.shape_type === "polygon") {
        event.preventDefault();
        setDraft((current) => {
          if (!current || current.points.length <= 2) {
            return null;
          }
          return { ...current, points: current.points.slice(0, -2) };
        });
      } else if (event.key === "Delete") {
        event.preventDefault();
        onDeleteActive();
      } else if (event.key === "Enter" && draft?.shape_type === "polygon" && draft.points.length >= 6) {
        event.preventDefault();
        commitNewObject("polygon", draft.points);
        setDraft(null);
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [draft, onDeleteActive]);

  function objectColor(object: AnnotationObject, index: number): string {
    return (
      (object.tag_id ? tagById.get(object.tag_id)?.color : undefined) ||
      tagByName.get(object.label.toLowerCase())?.color ||
      fallbackColors[index % fallbackColors.length]
    );
  }

  function clientPoint(event: { clientX: number; clientY: number }): Point {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect) {
      return { x: 0, y: 0 };
    }
    return { x: event.clientX - rect.left, y: event.clientY - rect.top };
  }

  function clientToImage(event: { clientX: number; clientY: number }): Point {
    const point = clientPoint(event);
    return clampPoint(
      {
        x: (point.x - transform.translateX) / transform.scale,
        y: (point.y - transform.translateY) / transform.scale
      },
      imageSize
    );
  }

  function commitNewObject(shapeType: AnnotationShapeType, points: number[]) {
    const label = activeLabel.trim() || "object";
    const nextObject: AnnotationObject = {
      client_id: makeClientId(),
      label,
      tag_id: activeTagId,
      shape_type: shapeType,
      points: shapeType === "rectangle" ? normalizeRectangle(points) : points,
      flags: {},
      attributes: {},
      group_id: null,
      z_order: objectsRef.current.length,
      locked: false,
      hidden: false,
      source: "manual",
      notes: null
    };
    const previous = objectsRef.current;
    const next = [...previous, nextObject];
    onObjectsCommit(next, previous);
    onActiveObjectChange(nextObject.client_id);
  }

  function handleBackgroundPointerDown(event: PointerEvent<SVGSVGElement>) {
    if (!imageSize) {
      return;
    }
    const point = clientToImage(event);
    const screenPoint = clientPoint(event);
    if (tool === "pan") {
      dragRef.current = { type: "pan", start: screenPoint, originalTransform: transform };
      event.currentTarget.setPointerCapture(event.pointerId);
      return;
    }
    if (tool === "rectangle") {
      const previousObjects = cloneObjects(objectsRef.current);
      dragRef.current = { type: "drawing-rectangle", start: point, previousObjects };
      setDraft({ shape_type: "rectangle", points: [point.x, point.y, point.x, point.y] });
      event.currentTarget.setPointerCapture(event.pointerId);
      return;
    }
    if (tool === "point") {
      commitNewObject("point", [point.x, point.y]);
      return;
    }
    if (tool === "polygon") {
      const currentDraft = draft;
      if (currentDraft?.points.length) {
        const first = { x: currentDraft.points[0], y: currentDraft.points[1] };
        if (currentDraft.points.length >= 6 && distance(first, point) <= 10 / transform.scale) {
          commitNewObject("polygon", currentDraft.points);
          setDraft(null);
          return;
        }
      }
      setDraft((current) =>
        current?.shape_type === "polygon"
          ? { ...current, points: [...current.points, point.x, point.y] }
          : { shape_type: "polygon", points: [point.x, point.y] }
      );
      return;
    }
    onActiveObjectChange(null);
  }

  function handleObjectPointerDown(event: PointerEvent<SVGElement>, object: AnnotationObject) {
    if (tool !== "select" || object.locked) {
      return;
    }
    event.stopPropagation();
    onActiveObjectChange(object.client_id);
    dragRef.current = {
      type: "object",
      clientId: object.client_id,
      start: clientToImage(event),
      previousObjects: cloneObjects(objectsRef.current)
    };
    svgRef.current?.setPointerCapture(event.pointerId);
  }

  function handleVertexPointerDown(event: PointerEvent<SVGCircleElement>, object: AnnotationObject, vertexIndex: number) {
    if (tool !== "select" || object.locked) {
      return;
    }
    event.stopPropagation();
    onActiveObjectChange(object.client_id);
    dragRef.current = {
      type: "vertex",
      clientId: object.client_id,
      vertexIndex,
      start: clientToImage(event),
      previousObjects: cloneObjects(objectsRef.current)
    };
    svgRef.current?.setPointerCapture(event.pointerId);
  }

  function handlePointerMove(event: PointerEvent<SVGSVGElement>) {
    const imagePoint = clientToImage(event);
    onStatusChange(
      imageSize
        ? `x ${imagePoint.x.toFixed(1)} / y ${imagePoint.y.toFixed(1)} · ${(transform.scale * 100).toFixed(0)}%`
        : "图片加载中"
    );

    const drag = dragRef.current;
    if (!drag) {
      if (draft?.shape_type === "polygon") {
        setDraft((current) => (current ? { ...current } : current));
      }
      return;
    }

    if (drag.type === "pan") {
      const point = clientPoint(event);
      setTransform({
        ...drag.originalTransform,
        translateX: drag.originalTransform.translateX + point.x - drag.start.x,
        translateY: drag.originalTransform.translateY + point.y - drag.start.y
      });
      return;
    }

    if (drag.type === "drawing-rectangle") {
      setDraft({
        shape_type: "rectangle",
        points: [drag.start.x, drag.start.y, imagePoint.x, imagePoint.y]
      });
      return;
    }

    const dx = imagePoint.x - drag.start.x;
    const dy = imagePoint.y - drag.start.y;
    const nextObjects = drag.previousObjects.map((object) => {
      if (object.client_id !== drag.clientId) {
        return object;
      }
      if (drag.type === "object") {
        return { ...object, points: movePoints(object.points, dx, dy) };
      }
      return updateVertex(object, drag.vertexIndex, { x: imagePoint.x, y: imagePoint.y });
    });
    objectsRef.current = nextObjects;
    onObjectsPreview(nextObjects);
  }

  function handlePointerUp(event: PointerEvent<SVGSVGElement>) {
    const drag = dragRef.current;
    if (!drag) {
      return;
    }
    if (drag.type === "drawing-rectangle" && draft?.shape_type === "rectangle") {
      const [xtl, ytl, xbr, ybr] = normalizeRectangle(draft.points);
      if (xbr - xtl >= 3 && ybr - ytl >= 3) {
        commitNewObject("rectangle", [xtl, ytl, xbr, ybr]);
      }
      setDraft(null);
    } else if (drag.type === "object" || drag.type === "vertex") {
      onObjectsCommit(objectsRef.current, drag.previousObjects);
    }
    dragRef.current = null;
    try {
      event.currentTarget.releasePointerCapture(event.pointerId);
    } catch {
      // Pointer capture may already be released by the browser.
    }
  }

  function handleWheel(event: WheelEvent<SVGSVGElement>) {
    if (!imageSize) {
      return;
    }
    event.preventDefault();
    const anchor = clientPoint(event);
    const imageAnchor = {
      x: (anchor.x - transform.translateX) / transform.scale,
      y: (anchor.y - transform.translateY) / transform.scale
    };
    const nextScale = Math.min(Math.max(transform.scale * (event.deltaY > 0 ? 0.9 : 1.1), 0.05), 20);
    setTransform({
      scale: nextScale,
      translateX: anchor.x - imageAnchor.x * nextScale,
      translateY: anchor.y - imageAnchor.y * nextScale
    });
  }

  const sortedObjects = useMemo(
    () => objects.map((object, index) => ({ object, index })).sort((a, b) => a.object.z_order - b.object.z_order),
    [objects]
  );
  const vertexRadius = Math.max(4 / transform.scale, 1.5);

  return (
    <div ref={wrapperRef} className="relative min-h-0 flex-1 overflow-hidden bg-gray-100">
      <svg
        ref={svgRef}
        className="h-full w-full touch-none"
        onPointerDown={handleBackgroundPointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={handlePointerUp}
        onWheel={handleWheel}
      >
        <g transform={`translate(${transform.translateX} ${transform.translateY}) scale(${transform.scale})`}>
          {imageSize && (
            <image
              href={imageUrl}
              x={0}
              y={0}
              width={imageSize.width}
              height={imageSize.height}
              preserveAspectRatio="none"
              pointerEvents="none"
            />
          )}
          {sortedObjects.map(({ object, index }) => {
            if (object.hidden) {
              return null;
            }
            const color = objectColor(object, index);
            const active = object.client_id === activeObjectId;
            const commonProps = {
              stroke: color,
              strokeWidth: active ? 3 : 2,
              vectorEffect: "non-scaling-stroke" as const,
              opacity: object.locked ? 0.55 : 1,
              onPointerDown: (event: PointerEvent<SVGElement>) => handleObjectPointerDown(event, object)
            };
            return (
              <g key={object.client_id}>
                {object.shape_type === "rectangle" && (
                  <rect
                    x={normalizeRectangle(object.points)[0]}
                    y={normalizeRectangle(object.points)[1]}
                    width={normalizeRectangle(object.points)[2] - normalizeRectangle(object.points)[0]}
                    height={normalizeRectangle(object.points)[3] - normalizeRectangle(object.points)[1]}
                    fill={`${color}22`}
                    {...commonProps}
                  />
                )}
                {object.shape_type === "polygon" && (
                  <polygon points={polygonPoints(object.points)} fill={`${color}22`} {...commonProps} />
                )}
                {object.shape_type === "point" && (
                  <circle
                    cx={object.points[0]}
                    cy={object.points[1]}
                    r={Math.max(6 / transform.scale, 2)}
                    fill={color}
                    {...commonProps}
                  />
                )}
                {object.shape_type === "points" &&
                  pairPoints(object.points).map((point, pointIndex) => (
                    <circle
                      key={pointIndex}
                      cx={point.x}
                      cy={point.y}
                      r={Math.max(5 / transform.scale, 2)}
                      fill={color}
                      {...commonProps}
                    />
                  ))}
                {active &&
                  !object.locked &&
                  getObjectVertices(object).map((point, vertexIndex) => (
                    <circle
                      key={`${object.client_id}-${vertexIndex}`}
                      cx={point.x}
                      cy={point.y}
                      r={vertexRadius}
                      fill="white"
                      stroke={color}
                      strokeWidth={2}
                      vectorEffect="non-scaling-stroke"
                      onPointerDown={(event) => handleVertexPointerDown(event, object, vertexIndex)}
                    />
                  ))}
              </g>
            );
          })}
          {draft?.shape_type === "rectangle" && (
            <rect
              x={normalizeRectangle(draft.points)[0]}
              y={normalizeRectangle(draft.points)[1]}
              width={normalizeRectangle(draft.points)[2] - normalizeRectangle(draft.points)[0]}
              height={normalizeRectangle(draft.points)[3] - normalizeRectangle(draft.points)[1]}
              fill="#11182722"
              stroke="#111827"
              strokeDasharray="6 4"
              strokeWidth={2}
              vectorEffect="non-scaling-stroke"
              pointerEvents="none"
            />
          )}
          {draft?.shape_type === "polygon" && (
            <g pointerEvents="none">
              <polyline
                points={polygonPoints(draft.points)}
                fill="none"
                stroke="#111827"
                strokeDasharray="6 4"
                strokeWidth={2}
                vectorEffect="non-scaling-stroke"
              />
              {pairPoints(draft.points).map((point, index) => (
                <circle
                  key={index}
                  cx={point.x}
                  cy={point.y}
                  r={index === 0 && draft.points.length >= 6 ? vertexRadius * 1.4 : vertexRadius}
                  fill={index === 0 && draft.points.length >= 6 ? "#111827" : "white"}
                  stroke="#111827"
                  strokeWidth={2}
                  vectorEffect="non-scaling-stroke"
                />
              ))}
            </g>
          )}
        </g>
      </svg>
      <img
        src={imageUrl}
        alt=""
        className="hidden"
        onLoad={(event) => {
          const image = event.currentTarget;
          setImageSize({ width: image.naturalWidth, height: image.naturalHeight });
          setFitKey((value) => value + 1);
        }}
      />
      <button
        type="button"
        onClick={fitImage}
        className="absolute bottom-4 right-4 rounded-lg border border-line bg-white px-3 py-2 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50"
      >
        适配
      </button>
      {tool === "polygon" && draft?.shape_type === "polygon" && draft.points.length >= 6 && (
        <button
          type="button"
          onClick={() => {
            commitNewObject("polygon", draft.points);
            setDraft(null);
          }}
          className="absolute bottom-4 left-4 rounded-lg bg-gray-900 px-3 py-2 text-sm font-medium text-white shadow-sm hover:bg-gray-800"
        >
          完成多边形
        </button>
      )}
    </div>
  );
}
