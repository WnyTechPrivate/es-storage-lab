import type {
  ClusterCreds, ClusterTestResponse, MeasurementRow,
  RunSummary, StartRunRequest, StartRunResponse, RunEvent,
  DataStreamInfo, DeleteResultItem,
} from "./types";

async function jpost<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}: ${await r.text()}`);
  return r.json();
}

async function jget<T>(path: string): Promise<T> {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}: ${await r.text()}`);
  return r.json();
}

export const api = {
  testCluster: (c: ClusterCreds) =>
    jpost<ClusterTestResponse>("/api/cluster/test", c),
  startRun: (req: StartRunRequest) =>
    jpost<StartRunResponse>("/api/runs", req),
  listRuns: () => jget<RunSummary[]>("/api/runs"),
  getRun: (id: string) => jget<RunSummary>(`/api/runs/${id}`),
  getMeasurements: (id: string) =>
    jget<MeasurementRow[]>(`/api/runs/${id}/measurements`),

  listDatastreams: (cluster: ClusterCreds) =>
    jpost<DataStreamInfo[]>("/api/cluster/datastreams", { cluster }),
  deleteDatastreams: (cluster: ClusterCreds, names: string[]) =>
    jpost<{ results: DeleteResultItem[] }>(
      "/api/cluster/datastreams/delete", { cluster, names }
    ),

  deleteRun: async (id: string): Promise<void> => {
    const r = await fetch(`/api/runs/${id}`, { method: "DELETE" });
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}: ${await r.text()}`);
  },
  remeasureRun: (id: string, cluster: ClusterCreds) =>
    jpost<MeasurementRow[]>(`/api/runs/${id}/remeasure`, cluster),
};

/** Subscribe to one run's event stream via SSE. Returns an unsubscribe fn. */
export function subscribeRunEvents(
  runId: string,
  onEvent: (ev: RunEvent) => void,
): () => void {
  const es = new EventSource(`/api/runs/${runId}/events`);
  es.onmessage = (m) => {
    try {
      const ev = JSON.parse(m.data) as RunEvent;
      onEvent(ev);
      if (ev.kind === "_end") es.close();
    } catch {
      // ignore non-JSON keepalives
    }
  };
  es.onerror = () => {
    // browser auto-reconnects; nothing to do
  };
  return () => es.close();
}
