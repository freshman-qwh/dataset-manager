import { FormEvent, useState } from "react";

import type { SplitPlanResult } from "../types/dataset";
import Modal from "./Modal";

interface SplitPlanModalProps {
  open: boolean;
  applying: boolean;
  result: SplitPlanResult | null;
  onClose: () => void;
  onApply: (payload: {
    train_ratio: number;
    val_ratio: number;
    test_ratio: number;
    include_test: boolean;
    stratify_by_tags: boolean;
    normal_only: boolean;
    only_unassigned: boolean;
    seed: number;
  }) => Promise<void>;
}

export default function SplitPlanModal({ open, applying, result, onClose, onApply }: SplitPlanModalProps) {
  const [train, setTrain] = useState(80);
  const [val, setVal] = useState(10);
  const [test, setTest] = useState(10);
  const [includeTest, setIncludeTest] = useState(true);
  const [stratify, setStratify] = useState(true);
  const [normalOnly, setNormalOnly] = useState(true);
  const [onlyUnassigned, setOnlyUnassigned] = useState(false);
  const [seed, setSeed] = useState(42);

  const effectiveTest = includeTest ? test : 0;
  const total = train + val + effectiveTest;
  const invalid = total <= 0 || train <= 0;

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (invalid) {
      return;
    }
    await onApply({
      train_ratio: train,
      val_ratio: val,
      test_ratio: effectiveTest,
      include_test: includeTest,
      stratify_by_tags: stratify,
      normal_only: normalOnly,
      only_unassigned: onlyUnassigned,
      seed
    });
  }

  return (
    <Modal open={open} title="数据集划分" onClose={onClose}>
      <form onSubmit={handleSubmit} className="max-h-[78vh] space-y-4 overflow-y-auto px-5 py-5">
        <div className="rounded-lg border border-line bg-gray-50 p-3 text-sm text-gray-600">
          按比例随机写入样本 split。开启标签分层时，多标签样本会同时参与每个标签的覆盖计算，尽量让少样本标签进入验证集和测试集。
        </div>
        <div className="grid gap-3 sm:grid-cols-3">
          <label className="block">
            <span className="text-sm font-medium text-gray-700">train</span>
            <input
              type="number"
              min={1}
              value={train}
              onChange={(event) => setTrain(Number(event.target.value))}
              className="mt-2 w-full rounded-lg border border-line px-3 py-2 text-sm outline-none focus:border-gray-900"
            />
          </label>
          <label className="block">
            <span className="text-sm font-medium text-gray-700">val</span>
            <input
              type="number"
              min={0}
              value={val}
              onChange={(event) => setVal(Number(event.target.value))}
              className="mt-2 w-full rounded-lg border border-line px-3 py-2 text-sm outline-none focus:border-gray-900"
            />
          </label>
          <label className="block">
            <span className="text-sm font-medium text-gray-700">test</span>
            <input
              type="number"
              min={0}
              value={test}
              disabled={!includeTest}
              onChange={(event) => setTest(Number(event.target.value))}
              className="mt-2 w-full rounded-lg border border-line px-3 py-2 text-sm outline-none focus:border-gray-900 disabled:bg-gray-100"
            />
          </label>
        </div>
        <div className="grid gap-2 text-sm text-gray-700 sm:grid-cols-2">
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={includeTest} onChange={(event) => setIncludeTest(event.target.checked)} />
            划分 test
          </label>
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={stratify} onChange={(event) => setStratify(event.target.checked)} />
            按标签分层
          </label>
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={normalOnly} onChange={(event) => setNormalOnly(event.target.checked)} />
            只处理正常文件
          </label>
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={onlyUnassigned} onChange={(event) => setOnlyUnassigned(event.target.checked)} />
            只处理未划分样本
          </label>
        </div>
        <label className="block">
          <span className="text-sm font-medium text-gray-700">随机种子</span>
          <input
            type="number"
            value={seed}
            onChange={(event) => setSeed(Number(event.target.value))}
            className="mt-2 w-full rounded-lg border border-line px-3 py-2 text-sm outline-none focus:border-gray-900"
          />
        </label>
        {result && (
          <div className="rounded-lg border border-line bg-gray-50 p-3 text-sm text-gray-700">
            <div>处理：{result.updated} / {result.requested}</div>
            <div>train：{result.train}</div>
            <div>val：{result.val}</div>
            <div>test：{result.test}</div>
            {result.warnings.length > 0 && (
              <div className="mt-2 max-h-28 overflow-auto rounded-md bg-white p-2 text-xs text-amber-700">
                {result.warnings.map((item) => (
                  <div key={item}>{item}</div>
                ))}
              </div>
            )}
          </div>
        )}
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-line px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
          >
            关闭
          </button>
          <button
            type="submit"
            disabled={applying || invalid}
            className="rounded-lg bg-gray-900 px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:bg-gray-300"
          >
            {applying ? "划分中" : "应用划分"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
