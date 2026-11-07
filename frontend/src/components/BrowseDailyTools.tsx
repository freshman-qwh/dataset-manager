import { useState } from "react";

import CoverageModal from "./CoverageModal";
import FilenameLookupModal from "./FilenameLookupModal";
import SampleCollectionsModal from "./SampleCollectionsModal";

interface Props {
  datasetId: number;
  sampleIds: number[];
}

/** Keep occasional tools together while the browse grid remains the main task. */
export default function BrowseDailyTools({ datasetId, sampleIds }: Props) {
  const [active, setActive] = useState<"lookup" | "basket" | "coverage" | null>(null);
  const [basketSampleIds, setBasketSampleIds] = useState<number[]>([]);
  const button = "min-h-9 rounded-lg border border-line bg-white px-3 py-2 text-xs text-gray-600 hover:bg-gray-50 disabled:opacity-40";

  function openBasket(ids: number[]) {
    setBasketSampleIds(ids);
    setActive("basket");
  }

  return (
    <div className="mb-3 rounded-xl border border-line bg-white px-3 py-2">
      <details>
        <summary className="cursor-pointer py-1 text-sm text-gray-600">找图、收集与覆盖检查</summary>
        <div className="mt-2 flex flex-wrap gap-2 border-t border-line pt-3">
          <button type="button" className={button} onClick={() => setActive("lookup")}>粘贴清单找图</button>
          <button type="button" className={button} onClick={() => openBasket(sampleIds)}>样本收集篮</button>
          <button type="button" className={button} onClick={() => setActive("coverage")}>类别 × 批次覆盖表</button>
        </div>
        <p className="mt-2 text-xs leading-5 text-gray-400">勾选图片后可跨文件夹收集，并从收集篮导出固定拼版。</p>
      </details>
      {sampleIds.length > 0 && <button type="button" className={`${button} mt-2`} onClick={() => openBasket(sampleIds)}>将所选 {sampleIds.length} 张加入收集篮</button>}
      {active === "lookup" && <FilenameLookupModal open datasetId={datasetId} onClose={() => setActive(null)} onSelect={openBasket} />}
      {active === "basket" && <SampleCollectionsModal open sampleIds={basketSampleIds} onClose={() => setActive(null)} />}
      {active === "coverage" && <CoverageModal open datasetId={datasetId} onClose={() => setActive(null)} />}
    </div>
  );
}
