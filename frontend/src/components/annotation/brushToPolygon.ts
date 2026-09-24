export interface BrushPoint {
  x: number;
  y: number;
}

export interface BrushImageSize {
  width: number;
  height: number;
}

type Vertex = { x: number; y: number };

function polygonArea(points: Vertex[]): number {
  return points.reduce((area, point, index) => {
    const next = points[(index + 1) % points.length];
    return area + point.x * next.y - next.x * point.y;
  }, 0) / 2;
}

function distanceToSegment(point: Vertex, start: Vertex, end: Vertex): number {
  const dx = end.x - start.x;
  const dy = end.y - start.y;
  const lengthSquared = dx * dx + dy * dy;
  const ratio = lengthSquared ? Math.max(0, Math.min(1, ((point.x - start.x) * dx + (point.y - start.y) * dy) / lengthSquared)) : 0;
  return Math.hypot(point.x - start.x - ratio * dx, point.y - start.y - ratio * dy);
}

function simplifyOpen(points: Vertex[], tolerance: number): Vertex[] {
  if (points.length <= 2) return points;
  let maximum = 0;
  let split = 0;
  for (let index = 1; index < points.length - 1; index += 1) {
    const distance = distanceToSegment(points[index], points[0], points[points.length - 1]);
    if (distance > maximum) {
      maximum = distance;
      split = index;
    }
  }
  if (maximum <= tolerance) return [points[0], points[points.length - 1]];
  return [...simplifyOpen(points.slice(0, split + 1), tolerance).slice(0, -1), ...simplifyOpen(points.slice(split), tolerance)];
}

function simplifyClosed(points: Vertex[], tolerance: number): Vertex[] {
  const first = points[0];
  let split = 1;
  for (let index = 2; index < points.length; index += 1) {
    if (Math.hypot(points[index].x - first.x, points[index].y - first.y)
      > Math.hypot(points[split].x - first.x, points[split].y - first.y)) split = index;
  }
  return [
    ...simplifyOpen(points.slice(0, split + 1), tolerance).slice(0, -1),
    ...simplifyOpen([...points.slice(split), first], tolerance).slice(0, -1)
  ];
}

/** Rasterize a brush stroke at image resolution, then trace its exposed pixel edges. */
export function brushToPolygon(stroke: BrushPoint[], radius: number, image: BrushImageSize): number[] {
  if (!stroke.length || stroke.length > 20_000 || !Number.isFinite(radius) || radius < 1
    || stroke.some((point) => !Number.isFinite(point.x) || !Number.isFinite(point.y))) {
    throw new Error("画笔笔迹无效或过长，请缩短单次绘制");
  }
  let left = stroke[0].x;
  let top = stroke[0].y;
  let right = left;
  let bottom = top;
  for (const point of stroke) {
    left = Math.min(left, point.x);
    top = Math.min(top, point.y);
    right = Math.max(right, point.x);
    bottom = Math.max(bottom, point.y);
  }
  const minX = Math.max(0, Math.floor(left - radius - 2));
  const minY = Math.max(0, Math.floor(top - radius - 2));
  const maxX = Math.min(image.width, Math.ceil(right + radius + 2));
  const maxY = Math.min(image.height, Math.ceil(bottom + radius + 2));
  const width = maxX - minX;
  const height = maxY - minY;
  if (width < 1 || height < 1) throw new Error("请在图片内绘制画笔区域");
  if (width * height > 4_000_000) throw new Error("画笔区域过大，请缩小范围后分段标注");

  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) throw new Error("浏览器无法处理画笔区域");
  context.lineCap = "round";
  context.lineJoin = "round";
  context.lineWidth = radius * 2;
  context.strokeStyle = "#000";
  context.fillStyle = "#000";
  context.beginPath();
  context.moveTo(stroke[0].x - minX, stroke[0].y - minY);
  for (const point of stroke.slice(1)) context.lineTo(point.x - minX, point.y - minY);
  context.stroke();
  if (stroke.length === 1) {
    context.beginPath();
    context.arc(stroke[0].x - minX, stroke[0].y - minY, radius, 0, Math.PI * 2);
    context.fill();
  }

  const data = context.getImageData(0, 0, width, height).data;
  const filled = (x: number, y: number): boolean => x >= 0 && y >= 0 && x < width && y < height && data[(y * width + x) * 4 + 3] >= 128;
  const edges = new Map<number, number[]>();
  const vertex = (x: number, y: number): number => y * (width + 1) + x;
  const addEdge = (from: number, to: number) => edges.set(from, [...(edges.get(from) ?? []), to]);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      if (!filled(x, y)) continue;
      if (!filled(x, y - 1)) addEdge(vertex(x, y), vertex(x + 1, y));
      if (!filled(x + 1, y)) addEdge(vertex(x + 1, y), vertex(x + 1, y + 1));
      if (!filled(x, y + 1)) addEdge(vertex(x + 1, y + 1), vertex(x, y + 1));
      if (!filled(x - 1, y)) addEdge(vertex(x, y + 1), vertex(x, y));
    }
  }
  if (!edges.size) throw new Error("画笔区域过小，请增大半径或笔迹");

  const loops: Vertex[][] = [];
  const edgeCount = [...edges.values()].reduce((total, next) => total + next.length, 0);
  while (edges.size) {
    const start = edges.keys().next().value as number;
    const loop: Vertex[] = [];
    let current = start;
    for (let step = 0; step <= edgeCount; step += 1) {
      loop.push({ x: current % (width + 1) + minX, y: Math.floor(current / (width + 1)) + minY });
      const outgoing = edges.get(current);
      if (!outgoing?.length) throw new Error("画笔轮廓不完整，请重新绘制");
      const next = outgoing.pop() as number;
      if (!outgoing.length) edges.delete(current);
      current = next;
      if (current === start) break;
    }
    if (current !== start) throw new Error("画笔轮廓过于复杂，请缩小绘制范围");
    loops.push(loop);
  }
  if (loops.length !== 1 || polygonArea(loops[0]) <= 0) {
    throw new Error("当前画笔区域包含孔洞或分离区域，请分别绘制或改用多边形");
  }
  let simplified = loops[0];
  for (let tolerance = 1; tolerance <= 8; tolerance += 1) {
    simplified = simplifyClosed(loops[0], tolerance);
    if (simplified.length <= 500) break;
  }
  if (simplified.length < 3 || simplified.length > 500 || Math.abs(polygonArea(simplified)) < 9) {
    throw new Error("无法可靠拟合当前画笔区域，请调整半径或改用多边形");
  }
  return simplified.flatMap((point) => [point.x, point.y]);
}
