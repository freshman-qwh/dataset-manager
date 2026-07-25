import { Download } from "lucide-react";

import type { TrainingReadinessConfigInput } from "../types/dataset";
import Modal from "./Modal";

export interface ExportPreview {
  title: string;
  filename: string;
  mimeType: string;
  content: string;
  summary: string;
  trainingConfig?: TrainingReadinessConfigInput;
}

interface ExportPreviewModalProps {
  preview: ExportPreview | null;
  onClose: () => void;
  onDownload: () => void;
}

export default function ExportPreviewModal({ preview, onClose, onDownload }: ExportPreviewModalProps) {
  if (!preview) {
    return null;
  }

  const visibleContent = preview.content.length > 12000 ? `${preview.content.slice(0, 12000)}\n...` : preview.content;

  return (
    <Modal open={Boolean(preview)} title="导出预览" onClose={onClose}>
      <div className="max-h-[78vh] space-y-4 overflow-y-auto px-5 py-5">
        <div className="rounded-lg border border-line bg-gray-50 p-3 text-sm text-gray-700">
          <div className="font-medium text-ink">{preview.title}</div>
          <div className="mt-1 break-all text-xs text-gray-500">文件名：{preview.filename}</div>
          <div className="mt-2 text-xs text-gray-600">{preview.summary}</div>
        </div>
        <pre className="max-h-96 overflow-auto rounded-lg border border-line bg-white p-3 text-xs leading-relaxed text-gray-700">
          {visibleContent}
        </pre>
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-line px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
          >
            取消
          </button>
          <button
            type="button"
            onClick={onDownload}
            className="inline-flex items-center justify-center gap-2 rounded-lg bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-800"
          >
            <Download size={17} />
            下载
          </button>
        </div>
      </div>
    </Modal>
  );
}
