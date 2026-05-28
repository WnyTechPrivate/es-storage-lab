import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis, Cell, ReferenceLine,
} from "recharts";
import { api } from "../lib/api";
import type { ClusterCreds, MeasurementRow, RunSummary } from "../lib/types";
import { Card } from "../ui/Card";
import { Badge } from "../ui/Badge";
import { Button } from "../ui/Button";
import { Field, Input } from "../ui/Input";
import { fmtBytes, fmtNum, fmtDelta, fmtTime, parseCaseName, labelOf, type AxisKey } from "../lib/format";

export function RunDetail() {
  const { id } = useParams<{ id: string }>();
  const [run, setRun] = useState<RunSummary | null>(null);
  const [rows, setRows] = useState<MeasurementRow[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<"ratio" | "size" | "case">("ratio");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [remeasureOpen, setRemeasureOpen] = useState<boolean>(false);
  const [remeasureBusy, setRemeasureBusy] = useState<boolean>(false);
  const [remeasureErr, setRemeasureErr] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    const rid = id;
    let stopped = false;
    async function refresh() {
      try {
        const r  = await api.getRun(rid);
        const ms = await api.getMeasurements(rid);
        if (stopped) return;
        setRun(r);
        setRows(ms);
        // stop polling once terminal
        if (r.status === "done" || r.status === "failed" || r.status === "cancelled") {
          stopped = true;
        }
      } catch (e) {
        if (!stopped) setErr(String(e));
      }
    }
    refresh();
    const t = setInterval(() => { if (!stopped) refresh(); }, 3000);
    return () => { stopped = true; clearInterval(t); };
  }, [id]);

  const cases = useMemo(() => rows.filter((r) => r.case_name !== "baseline"), [rows]);
  const rawSize = run?.raw_size_bytes ?? cases[0]?.raw_bytes ?? 0;

  const sorted = useMemo(() => {
    const arr = [...cases];
    arr.sort((a, b) => {
      let av: number | string = 0, bv: number | string = 0;
      if (sortKey === "ratio") { av = a.ratio_pri_over_raw ?? 0; bv = b.ratio_pri_over_raw ?? 0; }
      else if (sortKey === "size") { av = a.pri_store_bytes ?? 0; bv = b.pri_store_bytes ?? 0; }
      else { av = a.case_name; bv = b.case_name; }
      if (av < bv) return sortDir === "asc" ? -1 : 1;
      if (av > bv) return sortDir === "asc" ? 1 : -1;
      return 0;
    });
    return arr;
  }, [cases, sortKey, sortDir]);

  const ranking = useMemo(() => computeImpactRanking(cases), [cases]);
  const confounded = useMemo(() => detectConfounded(ranking), [ranking]);

  if (err) {
    return <div className="mx-auto max-w-5xl px-4 py-6 text-red-600">{err}</div>;
  }
  if (!run) {
    return <div className="mx-auto max-w-5xl px-4 py-6 text-gray-500">loading...</div>;
  }

  return (
    <div className="mx-auto max-w-6xl px-4 py-6 space-y-4">
      <div className="flex items-center justify-between">
        <Link to="/reports" className="text-brand-600 hover:underline text-sm">← Runs</Link>
        <div className="flex items-center gap-2">
          {(run.status === "done" || run.status === "failed") && (
            <Button variant="secondary" onClick={() => { setRemeasureErr(null); setRemeasureOpen(true); }}>
              다시 측정
            </Button>
          )}
          <Badge tone={run.status === "done" ? "success" : run.status === "failed" ? "danger" : "info"}>
            {run.status}
          </Badge>
        </div>
      </div>

      <Card title={<span>Run <code>{run.id}</code> · {run.label || "(no label)"}</span>}>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-y-2 gap-x-6 text-sm">
          <Info label="시각">{fmtTime(run.created_at)}</Info>
          <Info label="데이터셋">
            {run.dataset === "web"  ? <Badge tone="info">web</Badge>
             : run.dataset === "snmp" ? <Badge tone="warn">snmp</Badge>
             : <Badge>{run.dataset || "firewall"}</Badge>}
          </Info>
          <Info label="클러스터"><code>{run.cluster_host}</code></Info>
          <Info label="cases">{run.cases.length}</Info>
          <Info label="raw input">{fmtBytes(run.raw_size_bytes)} · {fmtNum(run.raw_docs)} docs</Info>
        </div>
      </Card>

      <Card title={<span>저장 크기</span>}>
        <div className="text-xs text-gray-500 mb-3">
          각 datastream 의 primary store 크기.
          비교용 raw input = <span className="font-semibold">{fmtBytes(rawSize)}</span>
        </div>
        <div className="h-[460px]">
          <ResponsiveContainer>
            <BarChart data={sorted} margin={{ top: 24, right: 80, left: 16, bottom: 60 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="case_name" interval={0} angle={-45} textAnchor="end" tick={{ fontSize: 10 }} height={60} />
              <YAxis
                width={70}
                domain={[0, (() => {
                  const m = Math.max(
                    rawSize || 0,
                    ...sorted.map((r) => r.pri_store_bytes ?? 0),
                  );
                  return Math.ceil(m * 1.15);
                })()]}
                tickCount={6}
                tickFormatter={(v: number) => fmtBytes(v)}
              />
              <Tooltip
                formatter={(v: number) => [fmtBytes(v), "저장 크기"]}
                labelFormatter={(l) => l as string}
              />
              <ReferenceLine
                y={rawSize}
                stroke="#1f2937"
                strokeDasharray="6 4"
                strokeWidth={2}
                ifOverflow="extendDomain"
                label={{
                  value: `원본 ${fmtBytes(rawSize)}`,
                  position: "right",
                  fill: "#1f2937",
                  fontSize: 11,
                  fontWeight: 600,
                }}
              />
              <Bar dataKey="pri_store_bytes" name="저장 크기">
                {sorted.map((r, i) => (
                  <Cell key={i} fill={(r.ratio_pri_over_raw ?? 1) < 1 ? "#10b981" : "#ef4444"} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Card>

      {remeasureOpen && (
        <RemeasureModal
          host={run.cluster_host || ""}
          busy={remeasureBusy}
          error={remeasureErr}
          onCancel={() => setRemeasureOpen(false)}
          onSubmit={async (creds) => {
            setRemeasureBusy(true);
            setRemeasureErr(null);
            try {
              const rows = await api.remeasureRun(run.id, creds);
              setRows(rows);
              setRemeasureOpen(false);
            } catch (e) {
              setRemeasureErr(String(e));
            } finally {
              setRemeasureBusy(false);
            }
          }}
        />
      )}

      <Card title={<span>케이스 표 ({sorted.length})</span>}>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-xs text-gray-600 sticky top-0 bg-white">
              <tr className="border-b">
                <Th onClick={() => toggleSort("case")} active={sortKey === "case"} dir={sortDir} align="center">Datastream</Th>
                <th className="py-2 text-center">Index mode</th>
                <th className="py-2 text-center">Source mode</th>
                <th className="py-2 text-center">Codec</th>
                <th className="py-2 text-center">Parsing</th>
                <Th onClick={() => toggleSort("size")} active={sortKey === "size"} dir={sortDir} align="center">Store size</Th>
                <th className="py-2 text-center">Docs</th>
                <th className="py-2 text-center">Size per doc</th>
                <Th onClick={() => toggleSort("ratio")} active={sortKey === "ratio"} dir={sortDir} align="center">원본 대비 증감율 (%)</Th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((r) => {
                const parsed = parseCaseName(r.case_name);
                const ratio = r.ratio_pri_over_raw ?? null;
                const tone = ratio == null ? "neutral" : ratio < 1 ? "success" : "danger";
                return (
                  <tr key={r.case_name} className="row-hover border-b last:border-0 text-center">
                    <td className="py-2 font-mono text-[11px]">{r.datastream}</td>
                    <td className="py-2">{labelOf("mode",    parsed?.mode)}</td>
                    <td className="py-2">{labelOf("src",     parsed?.src)}</td>
                    <td className="py-2">{labelOf("codec",   parsed?.codec)}</td>
                    <td className="py-2">{labelOf("parsing", parsed?.parsing)}</td>
                    <td className="py-2 tabular-nums">{fmtBytes(r.pri_store_bytes)}</td>
                    <td className="py-2 tabular-nums">{fmtNum(r.docs)}</td>
                    <td className="py-2 tabular-nums">
                      {r.docs && r.pri_store_bytes ? fmtBytes(r.pri_store_bytes / r.docs) : "-"}
                    </td>
                    <td className="py-2 tabular-nums">
                      <Badge tone={tone}>{fmtDelta(ratio)}</Badge>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>

      {ranking.length > 0 && (
        <Card title={<span>어떤 설정이 저장 공간을 가장 크게 바꾸는가</span>}>
          <div className="text-xs text-gray-500 mb-4">
            각 설정의 원본 대비 절약에 대한 결과 격차가 클수록, 그 설정이 저장 공간에 영향을 더 크게 줍니다.
            아래 숫자는 모두 <b>원본 로그 크기 = 0%</b> 기준의 변화량입니다.
          </div>
          <ol className="space-y-3">
            {ranking.map((r, idx) => {
              const tied = confounded.get(r.axis) ?? [];
              return (
                <li
                  key={r.axis}
                  className="rounded-lg border border-gray-200 bg-white px-4 py-3"
                >
                  <div className="flex items-baseline justify-between gap-3">
                    <div className="text-sm">
                      <span className="font-semibold text-gray-800">{idx + 1}위</span>
                      <span className="mx-2 text-gray-300">·</span>
                      <span className="font-medium text-gray-900">
                        {AXIS_HEADER[r.axis as AxisKey]}
                      </span>
                    </div>
                    <div className="text-xs text-gray-500 whitespace-nowrap">
                      격차 <span className="font-semibold text-gray-700 tabular-nums">
                        {(r.spread * 100).toFixed(1)}%p
                      </span>
                    </div>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-x-6 gap-y-2 text-sm">
                    {r.tokens.map((t) => {
                      const delta = (t.avg - 1) * 100;
                      const tone =
                        delta < -0.05 ? "text-emerald-700"
                        : delta > 0.05 ? "text-red-700"
                        : "text-gray-600";
                      return (
                        <div key={t.k} className="flex items-baseline gap-2">
                          <span className="text-gray-500">{labelOf(r.axis as AxisKey, t.k)}</span>
                          <span className={"tabular-nums font-semibold " + tone}>
                            {delta > 0 ? "+" : ""}{delta.toFixed(1)}%
                          </span>
                        </div>
                      );
                    })}
                  </div>
                  {tied.length > 0 && (
                    <div className="mt-3 rounded-md bg-amber-50 border border-amber-200 px-3 py-2 text-[11px] text-amber-800">
                      ※ <b>{tied.map((a) => AXIS_HEADER[a as AxisKey]).join(", ")}</b> 와(과)
                      항상 함께 움직이는 데이터입니다.
                      이번 비교에서는 두 설정의 효과를 따로 분리할 수 없으니, 분리하려면
                      Advanced 에서 codec 을 두 개 다 켜고 다시 실행하세요.
                    </div>
                  )}
                </li>
              );
            })}
          </ol>
        </Card>
      )}
    </div>
  );

  function toggleSort(k: "case" | "ratio" | "size") {
    if (sortKey === k) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else { setSortKey(k); setSortDir(k === "case" ? "asc" : "asc"); }
  }
}

function Info({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-xs text-gray-500">{label}</div>
      <div className="text-gray-800">{children}</div>
    </div>
  );
}

function Th({
  children, onClick, active, dir, align = "left",
}: {
  children: React.ReactNode;
  onClick: () => void;
  active: boolean;
  dir: "asc" | "desc";
  align?: "left" | "right" | "center";
}) {
  const alignCls = align === "right" ? "text-right" : align === "center" ? "text-center" : "text-left";
  return (
    <th className={"py-2 select-none cursor-pointer font-medium " + alignCls} onClick={onClick}>
      <span className={active ? "text-brand-700" : ""}>{children}</span>
      {active && <span className="ml-1 text-xs">{dir === "asc" ? "▲" : "▼"}</span>}
    </th>
  );
}

function RemeasureModal({
  host, busy, error, onCancel, onSubmit,
}: {
  host: string;
  busy: boolean;
  error: string | null;
  onCancel: () => void;
  onSubmit: (creds: ClusterCreds) => void;
}) {
  const savedUser = localStorage.getItem("es.user") || "elastic";
  const [user, setUser] = useState<string>(savedUser);
  const [password, setPassword] = useState<string>("");

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-xl shadow-xl max-w-md w-full p-5">
        <div className="text-lg font-semibold text-gray-900 mb-2">다시 측정</div>
        <div className="text-xs text-gray-500 mb-4">
          reindex 없이 클러스터의 기존 data stream 들에 대해 측정만 다시 실행합니다.
          (data stream 이 삭제됐다면 결과 없음)
        </div>
        <Field label="Host">
          <Input value={host} disabled />
        </Field>
        <Field label="Username">
          <Input value={user} onChange={(e) => setUser(e.target.value)} />
        </Field>
        <Field label="Password">
          <Input type="password" value={password} autoFocus
            onChange={(e) => setPassword(e.target.value)} />
        </Field>
        {error && (
          <div className="rounded-md bg-red-50 border border-red-200 p-2 text-xs text-red-700 whitespace-pre-wrap break-all">
            {error}
          </div>
        )}
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" onClick={onCancel} disabled={busy}>취소</Button>
          <Button
            disabled={busy || !host || !user || !password}
            onClick={() => onSubmit({ host, user, password })}
          >
            {busy ? "측정 중..." : "측정"}
          </Button>
        </div>
      </div>
    </div>
  );
}

const AXIS_HEADER: Partial<Record<AxisKey, string>> = {
  mode:    "Index mode",
  src:     "Source mode",
  codec:   "Codec",
  parsing: "Parsing",
};

type RankRow = { axis: string; tokens: { k: string; avg: number }[]; spread: number };

/** Two axes are "confounded" in this dataset if the sorted set of per-token
 *  averages is numerically identical — i.e. they move together and can't be
 *  separated. Returns axis → list of other axes it is tied with. */
function detectConfounded(ranking: RankRow[]): Map<string, string[]> {
  const groups = new Map<string, string[]>();
  for (const r of ranking) {
    if (r.tokens.length < 2) continue;
    const key = r.tokens
      .map((t) => t.avg.toFixed(4))
      .sort()
      .join("|");
    const arr = groups.get(key) ?? [];
    arr.push(r.axis);
    groups.set(key, arr);
  }
  const out = new Map<string, string[]>();
  for (const [, axes] of groups) {
    if (axes.length > 1) {
      for (const a of axes) {
        out.set(a, axes.filter((x) => x !== a));
      }
    }
  }
  return out;
}

function computeImpactRanking(rows: MeasurementRow[]): RankRow[] {
  const axes: ("mode" | "src" | "codec" | "parsing")[] = ["parsing", "mode", "src", "codec"];
  const out: RankRow[] = [];
  for (const axis of axes) {
    const groups: Record<string, number[]> = {};
    for (const r of rows) {
      const parsed = parseCaseName(r.case_name);
      if (!parsed || r.ratio_pri_over_raw == null) continue;
      const k = parsed[axis];
      (groups[k] ||= []).push(r.ratio_pri_over_raw);
    }
    const tokens = Object.entries(groups).map(([k, vals]) => ({
      k, avg: vals.reduce((a, b) => a + b, 0) / vals.length,
    })).sort((a, b) => b.avg - a.avg);   // larger avg (more "+") first, smaller (more "-") last
    if (tokens.length < 2) continue;
    const min = Math.min(...tokens.map((t) => t.avg));
    const max = Math.max(...tokens.map((t) => t.avg));
    out.push({ axis, tokens, spread: max - min });
  }
  return out.sort((a, b) => b.spread - a.spread);
}
