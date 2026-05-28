export function fmtBytes(n?: number | null): string {
  if (n == null) return "-";
  if (n < 1) return `${n.toFixed(3)} B`;
  if (n < 1024) return `${n.toFixed(n < 100 ? 1 : 0)} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(2)} MB`;
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

export function fmtPct(x?: number | null): string {
  if (x == null) return "-";
  return `${(x * 100).toFixed(1)}%`;
}

/** Express a store/raw ratio as a signed delta against raw=100%:
 *  ratio=0.29 → "-71.0%", ratio=1.06 → "+5.9%", ratio≈1 → "0%". */
export function fmtDelta(ratio?: number | null): string {
  if (ratio == null) return "-";
  const pct = (ratio - 1) * 100;
  if (Math.abs(pct) < 0.05) return "0%";
  return pct > 0 ? `+${pct.toFixed(1)}%` : `${pct.toFixed(1)}%`;
}

export function fmtNum(n?: number | null): string {
  if (n == null) return "-";
  return n.toLocaleString();
}

export function fmtTime(ts?: number | null): string {
  if (!ts) return "-";
  return new Date(ts * 1000).toLocaleString();
}

export function parseCaseName(name: string) {
  const parts = name.split(".");
  if (parts.length !== 6) return null;
  const [mode, src, codec, idx, dv, parsing] = parts;
  return { mode, src, codec, idx, dv, parsing };
}

/** Human labels for the case-axis tokens.
 *  Cells in the Report table use these — data stream names keep raw tokens. */
export const TOKEN_LABELS = {
  mode:    { ldb: "logsdb",    std: "standard", tsds: "TSDS" } as Record<string, string>,
  src:     { syn: "synthetic", str: "stored" } as Record<string, string>,
  codec:   { zstd: "ZSTD", lz4: "LZ4" } as Record<string, string>,
  idx:     { it: "true", if: "false" } as Record<string, string>,
  dv:      { dt: "true", df: "false" } as Record<string, string>,
  parsing: {
    p1: "event.original-only",
    p2: "event.original + parsed",
    p3: "parsed-only",
  } as Record<string, string>,
};

export type AxisKey = keyof typeof TOKEN_LABELS;

export function labelOf(axis: AxisKey, token: string | undefined): string {
  if (!token) return "-";
  return TOKEN_LABELS[axis][token] ?? token;
}
