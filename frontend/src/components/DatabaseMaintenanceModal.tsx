import { AlertTriangle, CheckCircle2, Database, RefreshCw, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  getDatabaseIntegrityReport,
  previewDatabaseIntegrityRepair,
  repairDatabaseIntegrity
} from "../api/client";
import type {
  DatabaseIntegrityReport,
  DatabaseRepairPreview,
  DatabaseRepairResult
} from "../types/system";
import Modal from "./Modal";

interface DatabaseMaintenanceModalProps {
  open: boolean;
  onClose: () => void;
}

const statusCopy = {
  healthy: {
    title: "数据库状态正常",
    detail: "结构与关联检查未发现需要处理的问题。",
    className: "border-emerald-200 bg-emerald-50 text-emerald-800",
    icon: CheckCircle2
  },
  attention: {
    title: "发现可检查的孤立元数据",
    detail: "先选择项目生成预览；只有输入确认文本后才会清理。",
    className: "border-amber-200 bg-amber-50 text-amber-800",
    icon: AlertTriangle
  },
  migration_required: {
    title: "数据库结构需要维护",
    detail: "请先停止后端并按维护文档完成升级，再处理孤立元数据。",
    className: "border-red-200 bg-red-50 text-red-800",
    icon: AlertTriangle
  }
};

export default function DatabaseMaintenanceModal({
  open,
  onClose
}: DatabaseMaintenanceModalProps) {
  const [report, setReport] = useState<DatabaseIntegrityReport | null>(null);
  const [selectedActionIds, setSelectedActionIds] = useState<string[]>([]);
  const [preview, setPreview] = useState<DatabaseRepairPreview | null>(null);
  const [result, setResult] = useState<DatabaseRepairResult | null>(null);
  const [confirmation, setConfirmation] = useState("");
  const [loading, setLoading] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [repairing, setRepairing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function loadReport() {
    setLoading(true);
    setError(null);
    try {
      const nextReport = await getDatabaseIntegrityReport();
      setReport(nextReport);
      setSelectedActionIds([]);
      setPreview(null);
      setResult(null);
      setConfirmation("");
    } catch {
      setError("完整性检查失败，请确认后端服务正在运行。");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (open) {
      void loadReport();
    }
  }, [open]);

  const selectedCount = useMemo(
    () =>
      report?.repair_actions
        .filter((action) => selectedActionIds.includes(action.action_id))
        .reduce((sum, action) => sum + action.affected_rows, 0) ?? 0,
    [report, selectedActionIds]
  );

  function toggleAction(actionId: string) {
    setSelectedActionIds((current) =>
      current.includes(actionId)
        ? current.filter((item) => item !== actionId)
        : [...current, actionId]
    );
    setPreview(null);
    setConfirmation("");
    setResult(null);
    setError(null);
  }

  async function handlePreview() {
    if (selectedActionIds.length === 0) {
      return;
    }
    setPreviewing(true);
    setError(null);
    try {
      setPreview(await previewDatabaseIntegrityRepair(selectedActionIds));
      setConfirmation("");
      setResult(null);
    } catch {
      setError("预览已过期或问题状态发生变化，请重新检查。");
    } finally {
      setPreviewing(false);
    }
  }

  async function handleRepair() {
    if (!preview || confirmation !== preview.confirmation_text) {
      return;
    }
    setRepairing(true);
    setError(null);
    try {
      const repairResult = await repairDatabaseIntegrity({
        report_token: preview.report_token,
        action_ids: preview.selected_actions.map((action) => action.action_id),
        confirmation
      });
      setResult(repairResult);
      setReport(repairResult.report);
      setSelectedActionIds([]);
      setPreview(null);
      setConfirmation("");
    } catch {
      setError("清理未执行。数据库可能已变化，请刷新后重新预览。");
    } finally {
      setRepairing(false);
    }
  }

  const status = report ? statusCopy[report.status] : null;
  const StatusIcon = status?.icon ?? Database;

  return (
    <Modal open={open} title="数据库维护" onClose={onClose} size="lg">
      <div className="max-h-[75vh] overflow-y-auto p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-sm font-medium text-ink">元数据完整性检查</p>
            <p className="mt-1 text-sm leading-6 text-gray-500">
              只检查 SQLite 元数据，不读取、移动或删除原始文件。
            </p>
          </div>
          <button
            type="button"
            onClick={() => void loadReport()}
            disabled={loading || repairing}
            className="inline-flex items-center gap-2 rounded-lg border border-line px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <RefreshCw className={loading ? "animate-spin" : ""} size={16} />
            重新检查
          </button>
        </div>

        {error && (
          <div role="alert" className="mt-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {loading && !report ? (
          <div className="mt-5 rounded-lg border border-line bg-gray-50 px-4 py-8 text-center text-sm text-gray-500">
            正在检查数据库…
          </div>
        ) : report && status ? (
          <>
            <div className={`mt-5 flex gap-3 rounded-lg border p-4 ${status.className}`}>
              <StatusIcon className="mt-0.5 shrink-0" size={19} />
              <div>
                <p className="text-sm font-semibold">{status.title}</p>
                <p className="mt-1 text-sm leading-6">{status.detail}</p>
              </div>
            </div>

            <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-3">
              <div className="rounded-lg border border-line bg-gray-50 px-3 py-3">
                <dt className="text-gray-500">SQLite 检查</dt>
                <dd className="mt-1 font-medium text-ink">{report.quick_check}</dd>
              </div>
              <div className="rounded-lg border border-line bg-gray-50 px-3 py-3">
                <dt className="text-gray-500">结构版本</dt>
                <dd className="mt-1 font-medium text-ink">
                  {report.current_revision ?? "尚未登记"} / {report.head_revision}
                </dd>
              </div>
              <div className="rounded-lg border border-line bg-gray-50 px-3 py-3">
                <dt className="text-gray-500">外键异常</dt>
                <dd className="mt-1 font-medium text-ink">{report.foreign_key_violation_count}</dd>
              </div>
            </dl>

            {report.schema_issues.length > 0 && (
              <section className="mt-5" aria-labelledby="database-schema-issues-title">
                <h3 id="database-schema-issues-title" className="text-sm font-semibold text-ink">
                  需要先升级结构
                </h3>
                <div className="mt-2 space-y-2">
                  {report.schema_issues.map((issue) => (
                    <div key={issue.code} className="rounded-lg border border-red-200 bg-red-50 px-3 py-3">
                      <p className="text-sm font-medium text-red-800">{issue.title}</p>
                      <p className="mt-1 text-xs leading-5 text-red-700">{issue.detail}</p>
                    </div>
                  ))}
                </div>
              </section>
            )}

            {report.status === "migration_required" && report.affected_row_count > 0 && (
              <p className="mt-3 rounded-lg border border-line bg-gray-50 px-3 py-3 text-sm text-gray-600">
                完成结构升级后，可继续预览 {report.affected_row_count} 条孤立元数据。
              </p>
            )}

            {report.status !== "migration_required" && report.repair_actions.length > 0 && (
              <section className="mt-5" aria-labelledby="database-repair-actions-title">
                <div className="flex items-end justify-between gap-3">
                  <div>
                    <h3 id="database-repair-actions-title" className="text-sm font-semibold text-ink">
                      可预览的清理项目
                    </h3>
                    <p className="mt-1 text-xs leading-5 text-gray-500">
                      默认不选择。清理前会自动创建可恢复的 SQLite 备份。
                    </p>
                  </div>
                  <span className="shrink-0 text-xs text-gray-500">已选 {selectedCount} 条</span>
                </div>

                <div className="mt-3 space-y-2">
                  {report.repair_actions.map((action) => {
                    const checked = selectedActionIds.includes(action.action_id);
                    return (
                      <label
                        key={action.action_id}
                        className={`flex cursor-pointer gap-3 rounded-lg border px-3 py-3 transition ${
                          checked ? "border-gray-900 bg-gray-50" : "border-line hover:bg-gray-50"
                        }`}
                      >
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() => toggleAction(action.action_id)}
                          disabled={repairing}
                          className="mt-1 h-4 w-4 rounded border-gray-300 text-gray-900 focus:ring-gray-900"
                        />
                        <span className="min-w-0">
                          <span className="flex flex-wrap items-center gap-2 text-sm font-medium text-ink">
                            {action.title}
                            <span className="rounded-md bg-white px-2 py-0.5 text-xs text-gray-600">
                              {action.affected_rows} 条
                            </span>
                          </span>
                          <span className="mt-1 block text-xs leading-5 text-gray-500">
                            {action.description}
                          </span>
                          {action.record_ids.length > 0 && (
                            <span className="mt-1 block break-all text-xs leading-5 text-gray-400">
                              记录标识：{action.record_ids.join("、")}
                              {action.truncated_record_ids > 0
                                ? `，另有 ${action.truncated_record_ids} 条`
                                : ""}
                            </span>
                          )}
                        </span>
                      </label>
                    );
                  })}
                </div>

                <button
                  type="button"
                  onClick={() => void handlePreview()}
                  disabled={selectedActionIds.length === 0 || previewing || repairing}
                  className="mt-4 inline-flex items-center gap-2 rounded-lg bg-gray-900 px-4 py-2.5 text-sm font-medium text-white hover:bg-gray-800 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <ShieldCheck size={16} />
                  {previewing ? "正在生成预览…" : "生成清理预览"}
                </button>
              </section>
            )}

            {preview && (
              <section className="mt-5 rounded-lg border border-amber-200 bg-amber-50 p-4" aria-labelledby="database-repair-confirm-title">
                <h3 id="database-repair-confirm-title" className="text-sm font-semibold text-amber-900">
                  最终确认
                </h3>
                <p className="mt-1 text-sm leading-6 text-amber-800">
                  将处理 {preview.affected_row_count} 条孤立元数据。系统会先创建并校验备份；原始文件不受影响。
                </p>
                <label className="mt-3 block text-sm font-medium text-amber-900">
                  输入“{preview.confirmation_text}”
                  <input
                    value={confirmation}
                    onChange={(event) => setConfirmation(event.target.value)}
                    disabled={repairing}
                    className="mt-2 w-full rounded-lg border border-amber-300 bg-white px-3 py-2.5 text-sm text-ink outline-none transition focus:border-amber-600"
                  />
                </label>
                <button
                  type="button"
                  onClick={() => void handleRepair()}
                  disabled={confirmation !== preview.confirmation_text || repairing}
                  className="mt-3 inline-flex items-center gap-2 rounded-lg bg-red-700 px-4 py-2.5 text-sm font-medium text-white hover:bg-red-800 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {repairing ? "正在备份并清理…" : "确认备份并清理"}
                </button>
              </section>
            )}

            {result && (
              <section className="mt-5 rounded-lg border border-emerald-200 bg-emerald-50 p-4" aria-live="polite">
                <div className="flex gap-3 text-emerald-800">
                  <CheckCircle2 className="mt-0.5 shrink-0" size={19} />
                  <div>
                    <p className="text-sm font-semibold">清理完成并已重新检查</p>
                    <p className="mt-1 text-sm leading-6">
                      删除 {result.deleted_rows} 条，更新 {result.updated_rows} 条；剩余可修复问题 {result.after_affected_row_count} 条。
                    </p>
                    <p className="mt-2 break-all text-xs leading-5">
                      恢复备份：{result.backup_path}
                    </p>
                  </div>
                </div>
              </section>
            )}
          </>
        ) : null}
      </div>
    </Modal>
  );
}
