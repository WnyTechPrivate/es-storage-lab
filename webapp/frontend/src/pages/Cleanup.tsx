import { useMemo, useState } from "react";
import { api } from "../lib/api";
import type { ClusterCreds, DataStreamInfo, DeleteResultItem } from "../lib/types";
import { Card } from "../ui/Card";
import { Button } from "../ui/Button";
import { Field, Input } from "../ui/Input";
import { Badge } from "../ui/Badge";
import { fmtBytes, fmtNum } from "../lib/format";

const DEFAULT_CREDS: ClusterCreds = {
  host: localStorage.getItem("es.host") || "https://192.168.200.71:9200",
  user: localStorage.getItem("es.user") || "elastic",
  password: "",
};

const FIXED_PATTERNS = [
  "logs-ldb*-*",
  "logs-std*-*",
  "logs-tsds*-*",
  "logs-baseline-*",
];

export function Cleanup() {
  const [creds, setCreds] = useState<ClusterCreds>(DEFAULT_CREDS);
  const [busy, setBusy] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [scanError, setScanError] = useState<string | null>(null);
  const [rows, setRows] = useState<DataStreamInfo[] | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [results, setResults] = useState<DeleteResultItem[] | null>(null);
  const [confirmOpen, setConfirmOpen] = useState<boolean>(false);

  async function scan() {
    setBusy(true); setError(null); setScanError(null); setResults(null);
    try {
      const r = await api.listDatastreams(creds);
      setRows(r);
      setPicked(new Set());
      localStorage.setItem("es.host", creds.host);
      localStorage.setItem("es.user", creds.user);
    } catch (e) {
      setScanError(String(e));
      setRows(null);
    } finally {
      setBusy(false);
    }
  }

  function togglePick(name: string) {
    setPicked((s) => {
      const next = new Set(s);
      if (next.has(name)) next.delete(name); else next.add(name);
      return next;
    });
  }

  function pickAll(on: boolean) {
    if (!rows) return;
    setPicked(on ? new Set(rows.map((r) => r.name)) : new Set());
  }

  const totals = useMemo(() => {
    if (!rows) return null;
    const sel = rows.filter((r) => picked.has(r.name));
    return {
      count: sel.length,
      bytes: sel.reduce((s, r) => s + (r.store_bytes || 0), 0),
      docs: sel.reduce((s, r) => s + (r.docs || 0), 0),
    };
  }, [rows, picked]);

  async function reallyDelete() {
    if (picked.size === 0) return;
    setBusy(true); setError(null); setConfirmOpen(false);
    try {
      const r = await api.deleteDatastreams(creds, Array.from(picked));
      setResults(r.results);
      // re-scan so the list reflects the new state
      await scan();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  const credsValid = creds.host.trim() && creds.user.trim() && creds.password;

  return (
    <div className="mx-auto max-w-6xl px-4 py-6 space-y-4">
      <Card title={<span>클러스터 연결</span>}>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <Field label="Host (URL)">
            <Input value={creds.host}
              onChange={(e) => setCreds({ ...creds, host: e.target.value })} />
          </Field>
          <Field label="Username">
            <Input value={creds.user}
              onChange={(e) => setCreds({ ...creds, user: e.target.value })} />
          </Field>
          <Field label="Password">
            <Input type="password" value={creds.password}
              onChange={(e) => setCreds({ ...creds, password: e.target.value })} />
          </Field>
        </div>
        <div className="flex items-end justify-between gap-3">
          <div className="text-xs text-gray-600">
            <div className="mb-1">조회 대상 패턴 (고정):</div>
            <div className="flex flex-wrap gap-2">
              {FIXED_PATTERNS.map((p) => (
                <code key={p} className="bg-gray-100 px-2 py-0.5 rounded">{p}</code>
              ))}
            </div>
          </div>
          <Button onClick={scan} disabled={!credsValid || busy}>
            {busy ? "조회 중..." : "조회"}
          </Button>
        </div>
        <div className="flex items-center gap-2 text-xs text-gray-500 mt-3">
          <Badge tone="warn">TLS 검증 비활성</Badge>
          <Badge tone="info">pipeline / index template 은 건드리지 않음</Badge>
        </div>
        {scanError && (
          <div className="mt-3 rounded-md bg-red-50 border border-red-200 p-3 text-sm text-red-700 whitespace-pre-wrap break-all">
            조회 실패: {scanError}
          </div>
        )}
      </Card>

      {rows && (
        <Card
          title={
            <div className="flex items-center justify-between w-full">
              <span>Datastreams ({rows.length})</span>
              {rows.length > 0 && (
                <div className="flex gap-2">
                  <Button variant="ghost" onClick={() => pickAll(true)}>전체 선택</Button>
                  <Button variant="ghost" onClick={() => pickAll(false)}>해제</Button>
                </div>
              )}
            </div>
          }
          footer={
            rows.length === 0 ? undefined : (
              <>
                <div className="mr-auto text-xs text-gray-500">
                  선택: <span className="font-semibold tabular-nums">{totals?.count ?? 0}</span> 개
                  · {fmtBytes(totals?.bytes)} · {fmtNum(totals?.docs)} docs
                </div>
                <Button
                  variant="danger"
                  disabled={busy || picked.size === 0}
                  onClick={() => setConfirmOpen(true)}
                >
                  선택 항목 삭제
                </Button>
              </>
            )
          }
        >
          {rows.length === 0 ? (
            <div className="text-sm text-gray-500">
              해당 패턴에 일치하는 datastream 이 없습니다.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-xs text-gray-600">
                  <tr className="border-b">
                    <th className="py-2 w-10"></th>
                    <th className="py-2 text-left font-medium">Name</th>
                    <th className="py-2 text-right font-medium">Backing #</th>
                    <th className="py-2 text-right font-medium">Docs</th>
                    <th className="py-2 text-right font-medium">Store</th>
                    <th className="py-2 text-left font-medium">Template</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.name} className="row-hover border-b last:border-0">
                      <td className="py-2 text-center">
                        <input
                          type="checkbox"
                          checked={picked.has(r.name)}
                          onChange={() => togglePick(r.name)}
                          className="h-4 w-4 accent-brand-600"
                        />
                      </td>
                      <td className="py-2 font-mono text-[12px]">{r.name}</td>
                      <td className="py-2 text-right tabular-nums">{r.backing_count}</td>
                      <td className="py-2 text-right tabular-nums">{fmtNum(r.docs)}</td>
                      <td className="py-2 text-right tabular-nums">{fmtBytes(r.store_bytes)}</td>
                      <td className="py-2 text-gray-500">{r.template || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}

      {results && (
        <Card title={<span>삭제 결과 ({results.length})</span>}>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-xs text-gray-600">
                <tr className="border-b">
                  <th className="py-2 text-left">Name</th>
                  <th className="py-2 text-left">결과</th>
                  <th className="py-2 text-left">에러</th>
                </tr>
              </thead>
              <tbody>
                {results.map((r, i) => (
                  <tr key={i} className="border-b last:border-0">
                    <td className="py-2 font-mono text-[12px]">{r.name}</td>
                    <td className="py-2">
                      {r.deleted
                        ? <Badge tone="success">deleted</Badge>
                        : <Badge tone="danger">failed</Badge>}
                    </td>
                    <td className="py-2 text-gray-500">{r.error || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {error && (
        <div className="rounded-md bg-red-50 border border-red-200 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {confirmOpen && totals && (
        <ConfirmModal
          count={totals.count}
          bytes={totals.bytes}
          onCancel={() => setConfirmOpen(false)}
          onConfirm={reallyDelete}
        />
      )}
    </div>
  );
}

function ConfirmModal({
  count, bytes, onCancel, onConfirm,
}: {
  count: number; bytes: number;
  onCancel: () => void; onConfirm: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-xl shadow-xl max-w-md w-full p-5">
        <div className="text-lg font-semibold text-gray-900 mb-2">정말 삭제할까요?</div>
        <div className="text-sm text-gray-700">
          선택한 <span className="font-semibold">{count}</span> 개 datastream 을 영구 삭제합니다
          (저장 크기 합 {fmtBytes(bytes)}).
        </div>
        <div className="text-xs text-gray-500 mt-2">
          이 작업은 되돌릴 수 없습니다. pipeline 과 index template 은 그대로 유지됩니다.
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="ghost" onClick={onCancel}>취소</Button>
          <Button variant="danger" onClick={onConfirm}>삭제</Button>
        </div>
      </div>
    </div>
  );
}
