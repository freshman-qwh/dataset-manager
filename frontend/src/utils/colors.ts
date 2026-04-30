import type { CSSProperties } from "react";

function hexToRgb(hex: string): { r: number; g: number; b: number } | null {
  const normalized = hex.trim().replace("#", "");
  if (!/^[0-9a-fA-F]{6}$/.test(normalized)) {
    return null;
  }
  return {
    r: Number.parseInt(normalized.slice(0, 2), 16),
    g: Number.parseInt(normalized.slice(2, 4), 16),
    b: Number.parseInt(normalized.slice(4, 6), 16)
  };
}

export function tagChipStyle(color?: string | null): CSSProperties {
  if (!color) {
    return {};
  }
  const rgb = hexToRgb(color);
  if (!rgb) {
    return {};
  }
  const luminance = (0.2126 * rgb.r + 0.7152 * rgb.g + 0.0722 * rgb.b) / 255;
  return {
    backgroundColor: color,
    borderColor: color,
    color: luminance > 0.62 ? "#111827" : "#ffffff"
  };
}
