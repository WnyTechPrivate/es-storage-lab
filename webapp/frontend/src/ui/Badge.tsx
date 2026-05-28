import type { ReactNode } from "react";

type Tone = "neutral" | "success" | "warn" | "danger" | "info";
const toneCls: Record<Tone, string> = {
  neutral: "bg-gray-100 text-gray-700",
  success: "bg-emerald-100 text-emerald-700",
  warn: "bg-amber-100 text-amber-800",
  danger: "bg-red-100 text-red-700",
  info: "bg-blue-100 text-blue-700",
};

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span className={`inline-block rounded px-2 py-0.5 text-[11px] font-medium ${toneCls[tone]}`}>
      {children}
    </span>
  );
}
