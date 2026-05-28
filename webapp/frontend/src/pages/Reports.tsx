import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import type { RunSummary } from "../lib/types";
import { Card } from "../ui/Card";
import { Badge } from "../ui/Badge";
import { Button } from "../ui/Button";
import { fmtBytes, fmtNum, fmtTime } from "../lib/format";

export function Reports() {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<RunSummary | null>(null);
  const [busy, setBusy] = useState<boolean>(false);

  async function refresh() {
    try {
      const rs = await api.listRuns();
      setRuns(rs);
    } catch (e) {
      setErr(String(e));
    }
  }

  useEffect(() => {
    let stopped = false;
    async function loop() {
      if (stopped) return;
      try {
        const rs = await api.listRuns();
        if (!stopped) setRuns(rs);
      } catch (e) {
        if (!stopped) setErr(String(e));
      }
    }
    loop();
    const t = setInterval(loop, 3000);
    return () => { stopped = true; clearInterval(t); };
  }, []);

  async function doDelete() {
    if (!pendingDelete) return;
    setBusy(true);
    try {
      await api.deleteRun(pendingDelete.id);
      setPendingDelete(null);
      await refresh();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-5xl px-4 py-6">
      <Card title={<span>Runs</span>}>
        {err && <div className="text-sm text-red-600">{err}</div>}
        {runs.length === 0 ? (
          <div className="text-sm text-gray-500">아직 실행한 run 이 없습니다.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-xs text-gray-600">
                <tr className="border-b">
                  <th className="py-2 text-left font-medium">시각</th>
                  <th className="py-2 text-left font-medium">라벨</th>
                  <th className="py-2 text-left font-medium">데이터셋</th>
                  <th className="py-2 text-left font-medium">상태</th>
                  <th className="py-2 text-left font-medium">클러스터</th>
                  <th className="py-2 text-right font-medium">cases</th>
                  <th className="py-2 text-right font-medium">raw size</th>
                  <th className="py-2 text-right font-medium">raw docs</th>
                  <th className="py-2 w-10"></th>
                </tr>
              </thead>
              <tbody>
                {runs.map((r) => (
                  <tr key={r.id} className="row-hover border-b last:border-0">
                    <td className="py-2 text-gray-700 whitespace-nowrap">
                      <Link to={`/report/${r.id}`} className="text-brand-600 hover:underline">
                        {fmtTime(r.created_at)}
                      </Link>
                    </td>
                    <td className="py-2 text-gray-800">{r.label || <span className="text-gray-400">—</span>}</td>
                    <td className="py-2">
                      {r.dataset === "web"  ? <Badge tone="info">web</Badge>
                       : r.dataset === "snmp" ? <Badge tone="warn">snmp</Badge>
                       : r.dataset === "firewall" ? <Badge>firewall</Badge>
                       : <span className="text-gray-400">—</span>}
                    </td>
                    <td className="py-2">
                      <StatusBadge status={r.status} />
                    </td>
                    <td className="py-2 text-gray-700"><code>{r.cluster_host}</code></td>
                    <td className="py-2 text-right tabular-nums">{r.cases.length}</td>
                    <td className="py-2 text-right tabular-nums">{fmtBytes(r.raw_size_bytes)}</td>
                    <td className="py-2 text-right tabular-nums">{fmtNum(r.raw_docs)}</td>
                    <td className="py-2 text-right">
                      <button
                        className="text-gray-400 hover:text-red-600 text-xs disabled:opacity-30"
                        title={r.status === "running" || r.status === "queued"
                          ? "진행 중인 run 은 삭제할 수 없습니다"
                          : "이 run 삭제"}
                        disabled={r.status === "running" || r.status === "queued"}
                        onClick={() => setPendingDelete(r)}
                      >
                        🗑
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {pendingDelete && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-white rounded-xl shadow-xl max-w-md w-full p-5">
            <div className="text-lg font-semibold text-gray-900 mb-2">이 run 을 삭제할까요?</div>
            <div className="text-sm text-gray-700 break-all">
              {pendingDelete.label
                ? <span className="font-semibold">{pendingDelete.label}</span>
                : <span className="text-gray-500">(no label)</span>}
              {" · "}
              <code className="text-xs">{pendingDelete.id}</code>
              {" · "}
              {fmtTime(pendingDelete.created_at)}
            </div>
            <div className="text-xs text-gray-500 mt-2">
              DB 에 저장된 run 정보와 측정값만 삭제됩니다. 클러스터의 data stream 은 그대로 유지됩니다
              (별도로 정리하려면 Cleanup 탭 이용).
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setPendingDelete(null)} disabled={busy}>취소</Button>
              <Button variant="danger" onClick={doDelete} disabled={busy}>
                {busy ? "삭제 중..." : "삭제"}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: RunSummary["status"] }) {
  if (status === "done") return <Badge tone="success">done</Badge>;
  if (status === "failed") return <Badge tone="danger">failed</Badge>;
  if (status === "running") return <Badge tone="info">running</Badge>;
  if (status === "queued") return <Badge tone="neutral">queued</Badge>;
  return <Badge>{status}</Badge>;
}
