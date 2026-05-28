export function Progress({ value, max = 100, label }: {
  value: number; max?: number; label?: string;
}) {
  const pct = max > 0 ? Math.min(100, Math.max(0, (value / max) * 100)) : 0;
  return (
    <div>
      {label && <div className="text-xs text-gray-600 mb-1">{label}</div>}
      <div className="h-2 w-full overflow-hidden rounded-full bg-gray-200">
        <div className="h-full bg-brand-500 transition-all" style={{ width: `${pct}%` }} />
      </div>
      <div className="mt-1 text-xs text-gray-500 tabular-nums">{pct.toFixed(1)}%</div>
    </div>
  );
}
