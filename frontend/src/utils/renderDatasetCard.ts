import { getSampleFileUrl, getSampleThumbnailUrl } from "../api/client";
import type { DatasetCard, DatasetCardPreview } from "../types/datasetCard";

export interface RenderedDatasetCard {
  blob: Blob;
  width: number;
  height: number;
  failedPreviews: number;
  loadedPreviews: number;
}

const WIDTH = 1600;
const PADDING = 80;
const INNER = WIDTH - PADDING * 2;
const FONT = '"Microsoft YaHei", "PingFang SC", system-ui, sans-serif';
const INK = "#111827";
const MUTED = "#6b7280";

function ensureActive(signal?: AbortSignal) {
  if (signal?.aborted) throw new DOMException("Generation cancelled", "AbortError");
}

function loadImage(url: string, signal?: AbortSignal): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    ensureActive(signal);
    const image = new Image();
    image.crossOrigin = "anonymous";
    image.decoding = "async";
    const cleanup = () => { window.clearTimeout(timer); image.onload = null; image.onerror = null; signal?.removeEventListener("abort", cancel); };
    const cancel = () => { cleanup(); image.removeAttribute("src"); reject(new DOMException("Generation cancelled", "AbortError")); };
    const timer = window.setTimeout(() => { cleanup(); image.removeAttribute("src"); reject(new Error("Image preview timed out")); }, 6000);
    image.onload = () => { cleanup(); image.naturalWidth > 0 ? resolve(image) : reject(new Error("Image preview is empty")); };
    image.onerror = () => { cleanup(); reject(new Error("Image preview unavailable")); };
    signal?.addEventListener("abort", cancel, { once: true });
    image.src = url;
  });
}

async function previewImage(sample: DatasetCardPreview, signal?: AbortSignal): Promise<HTMLImageElement | null> {
  try { return await loadImage(getSampleThumbnailUrl(sample.sample_id, sample.file_hash), signal); }
  catch { ensureActive(signal); }
  try { return await loadImage(getSampleFileUrl(sample.sample_id), signal); }
  catch { ensureActive(signal); return null; }
}

function font(context: CanvasRenderingContext2D, size: number, weight = 400) {
  context.font = `${weight} ${size}px ${FONT}`;
}

function clipped(context: CanvasRenderingContext2D, value: string, width: number): string {
  if (context.measureText(value).width <= width) return value;
  let result = "";
  for (const character of Array.from(value)) {
    if (context.measureText(result + character + "…").width > width) return result + "…";
    result += character;
  }
  return result;
}

function wrapped(context: CanvasRenderingContext2D, value: string, width: number, maxLines: number): string[] {
  const text = value.replace(/\s+/g, " ").trim();
  if (!text) return [];
  const chars = Array.from(text);
  const lines: string[] = [];
  let line = "";
  for (let index = 0; index < chars.length; index += 1) {
    const candidate = line + chars[index];
    if (context.measureText(candidate).width > width && line) {
      if (lines.length === maxLines - 1) {
        lines.push(clipped(context, line + chars.slice(index).join(""), width));
        return lines;
      }
      lines.push(line.trim()); line = chars[index];
    } else line = candidate;
  }
  if (line) lines.push(line.trim());
  return lines;
}

function panel(context: CanvasRenderingContext2D, x: number, y: number, width: number, height: number, fill = "#f7f8fa") {
  context.beginPath(); context.roundRect(x, y, width, height, 18);
  context.fillStyle = fill; context.fill();
}

function text(context: CanvasRenderingContext2D, value: string, x: number, y: number, size = 24, color = INK, weight = 400) {
  font(context, size, weight); context.fillStyle = color; context.fillText(value, x, y);
}

function number(value: number) { return value.toLocaleString("zh-CN"); }

/** Render one fixed layout locally. Only registered image previews are read. */
export async function renderDatasetCard(data: DatasetCard, signal?: AbortSignal): Promise<RenderedDatasetCard> {
  ensureActive(signal);
  await document.fonts.ready;
  ensureActive(signal);
  const samples = data.preview_samples.slice(0, 8);
  const images = await Promise.all(samples.map((sample) => previewImage(sample, signal)));
  ensureActive(signal);
  const categories = data.categories.slice(0, 12);
  const sampleRows = Math.max(1, Math.ceil(samples.length / 4));
  const categoryRows = Math.ceil(categories.length / 3);
  const canvas = document.createElement("canvas"); canvas.width = WIDTH;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("浏览器无法生成名片图片。");
  font(context, 54, 600);
  const title = wrapped(context, data.dataset.name, INNER, 2);
  font(context, 25);
  const description = wrapped(context, data.dataset.description || "本地数据集概览", INNER, 2);
  const titleBottom = 120 + title.length * 70;
  const statsY = Math.max(330, titleBottom + 58 + description.length * 36 + 30);
  const gridY = statsY + 330;
  const extraCategories = data.summary.category_count > categories.length;
  const height = gridY + sampleRows * 290 + (categories.length ? 90 + categoryRows * 72 : 0) + (extraCategories ? 35 : 0) + 130;
  canvas.height = height;
  context.fillStyle = "#ffffff"; context.fillRect(0, 0, WIDTH, height); context.textBaseline = "top";

  text(context, "DATASET MANAGER  /  数据集名片", PADDING, 64, 21, MUTED, 500);
  title.forEach((line, index) => text(context, line, PADDING, 120 + index * 70, 54, INK, 600));
  const project = data.dataset.project || "未归属项目";
  const task = data.dataset.workflow_profile === "industrial_anomaly" ? "工业异常检测" : data.dataset.task_capabilities.label;
  font(context, 24); text(context, clipped(context, `${project}  ·  ${task}`, INNER), PADDING, titleBottom + 10, 24, MUTED);
  description.forEach((line, index) => text(context, line, PADDING, titleBottom + 58 + index * 36, 25, MUTED));

  const statGap = 20; const statWidth = (INNER - statGap * 3) / 4;
  [["图片", data.summary.image_count], ["对象类别", data.summary.category_count], ["采集批次", data.summary.batch_count], ["关联 Mask", data.summary.mask_count]].forEach(([label, value], index) => {
    const x = PADDING + index * (statWidth + statGap);
    panel(context, x, statsY, statWidth, 125);
    text(context, String(label), x + 25, statsY + 22, 22, MUTED);
    font(context, 42, 600); text(context, clipped(context, number(Number(value)), statWidth - 50), x + 25, statsY + 58, 42, INK, 600);
  });
  const labels = [`正常 ${number(data.summary.normal_count)}`, `异常 ${number(data.summary.anomaly_count)}`, `待复核 ${number(data.summary.pending_count)}`, `未分拣 ${number(data.summary.untriaged_count)}`];
  labels.forEach((label, index) => text(context, label, PADDING + index * (INNER / 4), statsY + 156, 25, index === 1 ? "#9f413f" : MUTED));
  const split = data.summary.splits;
  text(context, `Train ${number(split.train)}   ·   Val ${number(split.val)}   ·   Test ${number(split.test)}   ·   未划分 ${number(split.unassigned)}`, PADDING, statsY + 210, 22, MUTED);

  text(context, "代表图片", PADDING, statsY + 275, 29, INK, 600);
  text(context, "按类别与已登记判定选取", PADDING + 155, statsY + 283, 20, MUTED);
  const tileGap = 20; const tileWidth = (INNER - tileGap * 3) / 4;
  if (!samples.length) {
    panel(context, PADDING, gridY, INNER, 245);
    text(context, data.summary.image_count ? "暂无可用代表图片" : "暂无已登记图片", PADDING + 40, gridY + 100, 30, MUTED);
  }
  samples.forEach((sample, index) => {
    const x = PADDING + (index % 4) * (tileWidth + tileGap); const y = gridY + Math.floor(index / 4) * 290;
    panel(context, x, y, tileWidth, 218);
    const image = images[index];
    if (image) {
      const ratio = Math.min((tileWidth - 24) / image.naturalWidth, 194 / image.naturalHeight);
      const width = image.naturalWidth * ratio; const imageHeight = image.naturalHeight * ratio;
      context.drawImage(image, x + (tileWidth - width) / 2, y + (218 - imageHeight) / 2, width, imageHeight);
    } else text(context, "预览不可用", x + 24, y + 93, 24, "#9ca3af");
    font(context, 23, 500); text(context, clipped(context, sample.category_name || sample.filename, tileWidth), x, y + 233, 23, INK, 500);
    const label = sample.label === "normal" ? "正常" : sample.label === "anomaly" ? "异常" : sample.label === "pending" ? "待复核" : "未分拣";
    text(context, label, x, y + 263, 19, MUTED);
  });

  let footerY = gridY + sampleRows * 290 + 40;
  if (categories.length) {
    text(context, "类别概览", PADDING, footerY, 29, INK, 600); footerY += 60;
    const cellWidth = (INNER - 32) / 3;
    categories.forEach((category, index) => {
      const x = PADDING + (index % 3) * (cellWidth + 16); const y = footerY + Math.floor(index / 3) * 72;
      panel(context, x, y, cellWidth, 57, "#f7f8fa");
      const count = `${number(category.sample_count)} 样本`;
      font(context, 21); const countWidth = context.measureText(count).width;
      font(context, 23, 500); text(context, clipped(context, category.name, cellWidth - countWidth - 56), x + 18, y + 17, 23, INK, 500);
      text(context, count, x + cellWidth - countWidth - 18, y + 18, 21, MUTED);
    });
    footerY += categoryRows * 72;
    if (data.summary.category_count > categories.length) { text(context, `另有 ${number(data.summary.category_count - categories.length)} 个类别`, PADDING, footerY + 2, 20, MUTED); footerY += 35; }
  }
  context.strokeStyle = "#e5e7eb"; context.lineWidth = 1; context.beginPath(); context.moveTo(PADDING, height - 95); context.lineTo(WIDTH - PADDING, height - 95); context.stroke();
  const generated = new Date(data.generated_at);
  const date = Number.isNaN(generated.getTime()) ? "时间未记录" : generated.toLocaleDateString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" });
  text(context, `生成于 ${date}  ·  统计来自已登记数据`, PADDING, height - 64, 20, MUTED);
  const failedPreviews = images.filter((image) => !image).length;
  const loadedPreviews = samples.length - failedPreviews;
  const footerNote = `登记 ${number(data.summary.sample_count)} 样本  ·  不可用 ${number(data.summary.unavailable_count)}  ·  代表图 ${loadedPreviews}/${samples.length} 已读取`;
  font(context, 20); const footerWidth = context.measureText(footerNote).width;
  text(context, footerNote, WIDTH - PADDING - footerWidth, height - 64, 20, MUTED);
  ensureActive(signal);
  const blob = await new Promise<Blob>((resolve, reject) => canvas.toBlob((value) => {
    if (signal?.aborted) reject(new DOMException("Generation cancelled", "AbortError"));
    else if (value) resolve(value); else reject(new Error("浏览器无法导出 PNG。"));
  }, "image/png"));
  return { blob, width: WIDTH, height, failedPreviews, loadedPreviews };
}
