import { FileText, Image as ImageIcon, ImageOff, Video } from "lucide-react";
import { useState } from "react";

import { getSampleFileUrl, getSampleThumbnailUrl } from "../api/client";

interface Props {
  sampleId: number | null;
  name: string;
  fileType?: string;
  fileStatus?: string;
  contentHash?: string;
  deferOriginal?: boolean;
}

export default function LocalBrowseThumbnail({ sampleId, name, fileType = "image", fileStatus = "normal", contentHash = "", deferOriginal = false }: Props) {
  const [failed, setFailed] = useState(false);
  const [thumbnailMissing, setThumbnailMissing] = useState(false);
  const [useOriginal, setUseOriginal] = useState(false);
  if (fileType !== "image") {
    return <span className="flex h-full w-full items-center justify-center text-gray-400">{fileType === "video" ? <Video size={30} /> : <FileText size={30} />}</span>;
  }
  if (sampleId === null || failed || fileStatus !== "normal") {
    return <span className="flex h-full w-full items-center justify-center text-gray-300"><ImageOff size={28} aria-label="没有可用预览" /></span>;
  }
  if (thumbnailMissing && deferOriginal) return <span className="flex h-full w-full items-center justify-center text-gray-300"><ImageIcon size={26} aria-label="正在准备缩略图" /></span>;
  const original = useOriginal || !contentHash || thumbnailMissing;
  return <img src={original ? getSampleFileUrl(sampleId) : getSampleThumbnailUrl(sampleId, contentHash)} alt={name} loading="lazy" className="h-full w-full object-contain" onError={() => { if (!original && contentHash) { setThumbnailMissing(true); if (!deferOriginal) setUseOriginal(true); } else setFailed(true); }} />;
}
