import { useEffect, useRef, useState } from "react";
import { API_BASE_URL, getSampleFileUrl } from "../api/client";

interface Props { sampleId: number; showMask: boolean; onDimensions: (value: string) => void; onFailed: (value: boolean) => void }

export default function BenchmarkImagePreview({ sampleId, showMask, onDimensions, onFailed }: Props) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [maskError, setMaskError] = useState("");
  useEffect(() => {
    let active = true;
    setMaskError("");
    const original = new Image();
    original.crossOrigin = "anonymous";
    original.onload = () => {
      if (!active || !canvas.current) return;
      const target = canvas.current;
      target.width = original.naturalWidth; target.height = original.naturalHeight;
      const context = target.getContext("2d");
      if (!context) return;
      context.drawImage(original, 0, 0);
      onDimensions(`${original.naturalWidth} × ${original.naturalHeight} px`);
      if (!showMask) return;
      const mask = new Image();
      mask.crossOrigin = "anonymous";
      mask.onload = () => {
        if (!active) return;
        if (mask.naturalWidth !== target.width || mask.naturalHeight !== target.height) { setMaskError("Mask 尺寸与原图不一致，未叠加。"); return; }
        try {
          const overlay = document.createElement("canvas");
          overlay.width = mask.naturalWidth; overlay.height = mask.naturalHeight;
          const overlayContext = overlay.getContext("2d");
          if (!overlayContext) return;
          overlayContext.drawImage(mask, 0, 0);
          const pixels = overlayContext.getImageData(0, 0, overlay.width, overlay.height);
          for (let index = 0; index < pixels.data.length; index += 4) {
            const foreground = pixels.data[index + 3] > 0 && (pixels.data[index] > 0 || pixels.data[index + 1] > 0 || pixels.data[index + 2] > 0);
            pixels.data[index] = 239; pixels.data[index + 1] = 68; pixels.data[index + 2] = 68;
            pixels.data[index + 3] = foreground ? 140 : 0;
          }
          overlayContext.putImageData(pixels, 0, 0);
          context.drawImage(overlay, 0, 0);
        } catch { if (active) setMaskError("Mask 无法叠加，原图仍可查看。"); }
      };
      mask.onerror = () => { if (active) setMaskError("Mask 文件不可用，请检查原始目录。"); };
      mask.src = `${API_BASE_URL}/samples/${sampleId}/mask`;
    };
    original.onerror = () => { if (active) onFailed(true); };
    original.src = getSampleFileUrl(sampleId);
    return () => { active = false; original.onload = null; original.onerror = null; };
  }, [onDimensions, onFailed, sampleId, showMask]);
  return <><canvas ref={canvas} aria-label={showMask ? "原图与官方 Mask 叠加" : "原图"} className="h-full w-full object-contain" />{maskError && <span role="alert" className="absolute bottom-2 left-2 right-2 rounded bg-white/95 px-3 py-2 text-xs text-amber-800">{maskError}</span>}</>;
}
