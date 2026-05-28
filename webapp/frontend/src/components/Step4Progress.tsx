import { useEffect, useMemo, useRef, useState } from "react";
import type { RunEvent } from "../lib/types";
import { api, subscribeRunEvents } from "../lib/api";
import { Card } from "../ui/Card";
import { Progress } from "../ui/Progress";
import { Badge } from "../ui/Badge";
import { Button } from "../ui/Button";
import { fmtBytes, fmtNum } from "../lib/format";

type Props = {
  runId: string;
  onDone: () => void;
  onFailed: (err: string) => void;
};

type Phase =
  | "starting" | "generate" | "locate" | "cleanup" | "setup"
  | "ingest" | "reindex" | "measure" | "done" | "failed";

export function Step4Progress({ runId, onDone, onFailed }: Props) {
  const [phase, setPhase] = useState<Phase>("starting");
  const [phaseMsg, setPhaseMsg] = useState<string>("starting run...");
  const [genPct, setGenPct] = useState<{ written: number; target: number }>({ written: 0, target: 0 });
  const [ingestPct, setIngestPct] = useState<{ sent: number; total: number }>({ sent: 0, total: 0 });
  const [caseProg, setCaseProg] = useState<{
    case_index: number; total_cases: number; case: string;
    sub_phase: string; created: number; total: number;
  } | null>(null);
  const [log, setLog] = useState<string[]>([]);
  const [doneCases, setDoneCases] = useState<{ case: string; created: number }[]>([]);
  const [allCases, setAllCases] = useState<string[]>([]);
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const unsubscribe = subscribeRunEvents(runId, (ev) => handleEvent(ev));
    // Fallback: poll run status every 2s, so we still surface done/failed
    // even if the SSE stream stalls or the browser blocks EventSource.
    const poll = setInterval(async () => {
      try {
        const r = await api.getRun(runId);
        if (r.status === "done") {
          setPhase("done"); setPhaseMsg("완료");
          onDone();
          clearInterval(poll);
        } else if (r.status === "failed") {
          setPhase("failed"); setPhaseMsg("실패");
          onFailed("run failed");
          clearInterval(poll);
        }
      } catch { /* ignore transient errors */ }
    }, 2000);
    return () => { unsubscribe(); clearInterval(poll); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [log]);

  function appendLog(s: string) {
    setLog((arr) => [...arr.slice(-500), s]);
  }

  function handleEvent(ev: RunEvent) {
    switch (ev.kind) {
      case "run_started":
        setAllCases((ev.cases as string[]) || []);
        appendLog(`run started — ${(ev.cases as string[])?.length} cases`);
        break;
      case "phase":
        setPhase((ev.phase as Phase) ?? "starting");
        setPhaseMsg((ev.message as string) ?? "");
        appendLog(`[phase] ${ev.phase}: ${ev.message ?? ""}`);
        break;
      case "generate_progress":
        setGenPct({ written: ev.written as number, target: ev.target as number });
        break;
      case "raw_ready":
        appendLog(`raw input ready · ${fmtBytes(ev.bytes as number)} · ${fmtNum(ev.docs as number)} docs`);
        break;
      case "ingest_progress":
        setIngestPct({ sent: ev.sent as number, total: ev.total as number });
        break;
      case "ingest_done":
        appendLog(`ingest done · sent=${fmtNum(ev.docs_sent as number)} errors=${ev.errors}`);
        break;
      case "case_progress":
        setCaseProg({
          case_index: ev.case_index as number,
          total_cases: ev.total_cases as number,
          case: ev.case as string,
          sub_phase: ev.sub_phase as string,
          created: ev.created as number,
          total: ev.total as number,
        });
        if (ev.sub_phase === "done") {
          setDoneCases((arr) => [...arr, { case: ev.case as string, created: ev.created as number }]);
          appendLog(`[case ${ev.case_index}/${ev.total_cases}] ${ev.case} ✓ created=${ev.created}`);
        }
        break;
      case "reindex_done":
        appendLog(`reindex done · ${(ev.results as unknown[])?.length} cases`);
        break;
      case "measure_done":
        appendLog(`measure done · ${ev.n_rows} rows`);
        break;
      case "log":
        appendLog(String(ev.message));
        break;
      case "run_done":
        setPhase("done");
        setPhaseMsg("완료");
        appendLog("RUN DONE");
        onDone();
        break;
      case "run_failed":
        setPhase("failed");
        setPhaseMsg(String(ev.error));
        appendLog(`RUN FAILED: ${ev.error}`);
        onFailed(String(ev.error));
        break;
    }
  }

  const overallPct = useMemo(() => {
    if (!caseProg) return 0;
    const per = caseProg.total > 0 ? caseProg.created / caseProg.total : 0;
    const completed = (caseProg.case_index - 1) + per;
    return Math.min(100, (completed / caseProg.total_cases) * 100);
  }, [caseProg]);

  const isDone = phase === "done";
  const isFailed = phase === "failed";

  return (
    <Card title={<span>Step 4 · 실행 중 — run <code>{runId}</code></span>}>
      <div className="mb-4 flex items-center gap-2">
        <Badge tone={isDone ? "success" : isFailed ? "danger" : "info"}>
          {isDone ? "완료" : isFailed ? "실패" : "진행 중"}
        </Badge>
        <span className="text-sm text-gray-700">{phase} · {phaseMsg}</span>
      </div>

      {phase === "generate" && (
        <div className="mb-4">
          <div className="text-xs text-gray-600 mb-1">
            로그 생성 · {fmtBytes(genPct.written)} / {fmtBytes(genPct.target)}
          </div>
          <Progress value={genPct.written} max={Math.max(1, genPct.target)} />
        </div>
      )}

      {phase === "ingest" && (
        <div className="mb-4">
          <div className="text-xs text-gray-600 mb-1">
            baseline 인입 · {fmtNum(ingestPct.sent)} / {fmtNum(ingestPct.total)} docs
          </div>
          <Progress value={ingestPct.sent} max={Math.max(1, ingestPct.total)} />
        </div>
      )}

      {(phase === "reindex" || phase === "measure" || isDone) && (
        <div className="mb-4">
          <div className="text-xs text-gray-600 mb-1">
            전체 진행 ·{" "}
            {caseProg
              ? `${caseProg.case_index}/${caseProg.total_cases}  (${caseProg.case})`
              : "준비 중"}
          </div>
          <Progress value={overallPct} max={100} />
          {caseProg && caseProg.sub_phase === "reindex" && (
            <div className="mt-3 text-xs text-gray-500">
              현재 케이스 reindex: {fmtNum(caseProg.created)} / {fmtNum(caseProg.total)}
              <Progress value={caseProg.created} max={Math.max(1, caseProg.total)} />
            </div>
          )}
          {caseProg && caseProg.sub_phase === "forcemerge" && (
            <div className="mt-2 text-xs text-gray-500">force_merge 중…</div>
          )}
        </div>
      )}

      <div className="mt-4">
        <div className="text-xs font-medium text-gray-700 mb-2">
          완료된 케이스 ({doneCases.length}/{allCases.length || "?"})
        </div>
        <div className="flex flex-wrap gap-2">
          {allCases.map((c) => {
            const done = doneCases.find((x) => x.case === c);
            const current = caseProg?.case === c && !done;
            return (
              <span
                key={c}
                className={
                  "rounded-md px-2 py-1 text-[11px] font-mono " +
                  (done ? "bg-emerald-100 text-emerald-700"
                   : current ? "bg-blue-100 text-blue-700"
                   : "bg-gray-100 text-gray-500")
                }
              >
                {c}
              </span>
            );
          })}
        </div>
      </div>

      <details className="mt-5">
        <summary className="text-xs text-gray-600 cursor-pointer">로그 (펼치기)</summary>
        <div
          ref={logRef}
          className="mt-2 max-h-56 overflow-y-auto rounded-md border border-gray-200 bg-gray-900 text-gray-100 p-3 text-[11px] font-mono whitespace-pre-wrap"
        >
          {log.map((l, i) => <div key={i}>{l}</div>)}
        </div>
      </details>

      {(isDone || isFailed) && (
        <div className="mt-5 flex justify-end gap-2">
          <Button onClick={onDone}>리포트 보기 →</Button>
        </div>
      )}
    </Card>
  );
}
