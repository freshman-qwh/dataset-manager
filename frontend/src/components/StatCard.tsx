import type { ReactNode } from "react";

interface StatCardProps {
  label: string;
  value: string | number;
  icon: ReactNode;
  tone?: "neutral" | "info" | "warning" | "danger";
  actionLabel?: string;
  onClick?: () => void;
}

const toneClass = {
  neutral: "border-line bg-white text-ink",
  info: "border-blue-200 bg-blue-50 text-blue-900",
  warning: "border-amber-200 bg-amber-50 text-amber-900",
  danger: "border-red-200 bg-red-50 text-red-900"
};

export default function StatCard({ label, value, icon, tone = "neutral", actionLabel, onClick }: StatCardProps) {
  const content = (
    <>
      <div className="flex items-center justify-between">
        <span className={tone === "neutral" ? "text-sm text-gray-500" : "text-sm font-medium opacity-80"}>{label}</span>
        <span className={tone === "neutral" ? "text-gray-400" : "opacity-70"}>{icon}</span>
      </div>
      <div className="mt-3 text-2xl font-semibold tracking-normal text-ink">{value}</div>
      {actionLabel && <div className="mt-2 text-xs font-medium opacity-70">{actionLabel}</div>}
    </>
  );

  if (onClick) {
    return (
      <button
        type="button"
        onClick={onClick}
        className={`rounded-lg border px-4 py-4 text-left shadow-sm transition hover:-translate-y-0.5 hover:shadow-soft ${toneClass[tone]}`}
      >
        {content}
      </button>
    );
  }

  return (
    <div className={`rounded-lg border px-4 py-4 shadow-sm ${toneClass[tone]}`}>
      {content}
    </div>
  );
}
