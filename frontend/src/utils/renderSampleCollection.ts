import { getSampleFileUrl } from "../api/client";
import type { SampleCollection } from "../types/sampleCollections";

async function verifiedImage(sampleId: number, expectedHash: string, signal: AbortSignal): Promise<{ image: HTMLImageElement; url: string }> {
  const response = await fetch(getSampleFileUrl(sampleId), { signal, cache: "no-store" });
  if (!response.ok) throw new Error(`图片 #${sampleId} 读取失败，请检查原文件后重试。`);
  const bytes = await response.arrayBuffer();
  const hash = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)), (byte) => byte.toString(16).padStart(2, "0")).join("");
  if (hash !== expectedHash.toLowerCase()) throw new Error(`图片 #${sampleId} 已变化，请重新扫描并重新加入收集篮。`);
  const url = URL.createObjectURL(new Blob([bytes], { type: response.headers.get("Content-Type") ?? "image/png" }));
  try {
    const image = new Image();
    image.src = url;
    await image.decode();
    signal.throwIfAborted();
    if (!image.naturalWidth) throw new Error("图片为空。");
    return { image, url };
  } catch (error) { URL.revokeObjectURL(url); throw error; }
}

function clipped(context: CanvasRenderingContext2D, value: string, width: number): string {
  if (context.measureText(value).width <= width) return value;
  let result = value;
  while (result.length && context.measureText(`${result}…`).width > width) result = result.slice(0, -1);
  return `${result}…`;
}

export async function renderSampleCollection(collection: SampleCollection, page: number, pageSize: 4 | 9 | 16, signal: AbortSignal): Promise<Blob> {
  const offset = (page - 1) * pageSize;
  const entries = collection.items.slice(offset, offset + pageSize);
  if (!entries.length || entries.some((item) => item.unavailable_reason || !item.sample)) throw new Error("本页有不可用图片，请先检查或移除后再生成拼版。");
  let loaded: { image: HTMLImageElement; url: string } | null = null;
  try {
    signal.throwIfAborted();
    const columns = Math.sqrt(pageSize);
    const cell = 470;
    const padding = 35;
    const top = 115;
    const canvas = document.createElement("canvas");
    canvas.width = columns * cell + padding * 2;
    canvas.height = columns * (cell + 100) + top + padding;
    const context = canvas.getContext("2d");
    if (!context) throw new Error("浏览器无法生成拼版。");
    context.fillStyle = "#ffffff"; context.fillRect(0, 0, canvas.width, canvas.height);
    const font = '"Microsoft YaHei", "PingFang SC", sans-serif';
    context.fillStyle = "#111827"; context.font = `bold 30px ${font}`;
    context.fillText(clipped(context, collection.name, canvas.width - padding * 2), padding, 48);
    context.fillStyle = "#6b7280"; context.font = `20px ${font}`;
    context.fillText(`第 ${page} / ${Math.ceil(collection.items.length / pageSize)} 页 · 图片 ${offset + 1}–${offset + entries.length} / ${collection.items.length} · 完整来源见清单`, padding, 84);
    for (let index = 0; index < entries.length; index += 1) {
      const item = entries[index];
      // Verify and draw one source at a time, releasing large decoded originals
      // immediately. Failed pages never produce an exportable artifact.
      loaded = await verifiedImage(item.sample_id, item.file_hash, signal);
      const image = loaded.image;
      const x = padding + index % columns * cell;
      const y = top + Math.floor(index / columns) * (cell + 100);
      const inner = cell - 20;
      context.fillStyle = "#f3f4f6"; context.fillRect(x, y, inner, cell - 35);
      const ratio = Math.min(inner / image.naturalWidth, (cell - 35) / image.naturalHeight);
      const width = image.naturalWidth * ratio; const height = image.naturalHeight * ratio;
      context.drawImage(image, x + (inner - width) / 2, y + (cell - 35 - height) / 2, width, height);
      context.fillStyle = "#111827"; context.font = `bold 20px ${font}`;
      context.fillText(clipped(context, `${offset + index + 1}. ${item.filename}`, inner), x, y + cell - 6);
      context.fillStyle = "#6b7280"; context.font = `18px ${font}`;
      const sample = item.sample!;
      const status = ({ ok: "正常", ng: "异常", pending: "待定", untriaged: "未分拣" } as const)[sample.triage_status];
      context.fillText(clipped(context, `数据集 #${item.dataset_id} · ${sample.category_id ? `类别 #${sample.category_id} · ` : ""}${status}`, inner), x, y + cell + 22);
      context.fillText(clipped(context, item.note || sample.benchmark_defect_type || "", inner), x, y + cell + 50);
      URL.revokeObjectURL(loaded.url); image.removeAttribute("src"); loaded = null;
    }
    signal.throwIfAborted();
    return await new Promise<Blob>((resolve, reject) => canvas.toBlob((blob) => blob ? resolve(blob) : reject(new Error("PNG 生成失败。")), "image/png"));
  } finally { if (loaded) { URL.revokeObjectURL(loaded.url); loaded.image.removeAttribute("src"); } }
}
