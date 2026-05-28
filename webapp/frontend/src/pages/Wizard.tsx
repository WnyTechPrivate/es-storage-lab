import { useState } from "react";
import { useNavigate } from "react-router-dom";
import type {
  CaseAxes, ClusterCreds, ClusterTestResponse, IngestGenerated,
} from "../lib/types";
import { Step1Cluster } from "../components/Step1Cluster";
import { Step2Ingest } from "../components/Step2Ingest";
import { Step3Cases } from "../components/Step3Cases";
import { Step4Progress } from "../components/Step4Progress";
import { api } from "../lib/api";

const DEFAULT_CREDS: ClusterCreds = {
  host: localStorage.getItem("es.host") || "https://192.168.200.71:9200",
  user: localStorage.getItem("es.user") || "elastic",
  password: "",
};

const DEFAULT_INGEST: IngestGenerated = {
  mode: "generated", dataset: "firewall", target_bytes: 10 * 1024 * 1024, seed: 42,
};
const DEFAULT_AXES: CaseAxes = {
  modes: ["std", "ldb"],
  sources: ["str", "syn"],
  codecs: ["lz4", "zstd"],
  parsings: ["p1", "p2", "p3"],
};

export function Wizard() {
  const nav = useNavigate();
  const [step, setStep] = useState<1 | 2 | 3 | 4>(1);
  const [creds, setCreds] = useState<ClusterCreds>(DEFAULT_CREDS);
  const [_test, setTest] = useState<ClusterTestResponse | null>(null);
  const [ingest, setIngest] = useState<IngestGenerated>(DEFAULT_INGEST);
  const [axes, setAxes] = useState<CaseAxes>(DEFAULT_AXES);
  const [label, setLabel] = useState<string>("");
  const [runId, setRunId] = useState<string | null>(null);
  const [startError, setStartError] = useState<string | null>(null);

  async function startRun(finalAxes: CaseAxes, finalLabel?: string) {
    setStartError(null);
    setAxes(finalAxes);
    if (finalLabel != null) setLabel(finalLabel);
    try {
      const r = await api.startRun({
        label: finalLabel,
        cluster: creds,
        ingest,
        cases: finalAxes,
        cleanup_first: true,
      });
      setRunId(r.run_id);
      setStep(4);
      localStorage.setItem("es.host", creds.host);
      localStorage.setItem("es.user", creds.user);
    } catch (e) {
      setStartError(String(e));
    }
  }

  return (
    <div className="mx-auto max-w-5xl px-4 py-6">
      <Steps current={step} />

      {step === 1 && (
        <Step1Cluster
          initial={creds}
          onConfirmed={(c, t) => { setCreds(c); setTest(t); setStep(2); }}
        />
      )}
      {step === 2 && (
        <Step2Ingest
          initial={ingest}
          onBack={() => setStep(1)}
          onConfirmed={(ing) => { setIngest(ing); setStep(3); }}
        />
      )}
      {step === 3 && (
        <Step3Cases
          initial={axes}
          initialLabel={label}
          onBack={() => setStep(2)}
          onConfirmed={(a, l) => startRun(a, l)}
        />
      )}
      {startError && (
        <div className="mt-4 rounded-md bg-red-50 border border-red-200 p-3 text-sm text-red-700">
          run 시작 실패: {startError}
        </div>
      )}
      {step === 4 && runId && (
        <Step4Progress
          runId={runId}
          onDone={() => nav(`/report/${runId}`)}
          onFailed={() => {/* stay on screen */}}
        />
      )}
    </div>
  );
}

function Steps({ current }: { current: 1 | 2 | 3 | 4 }) {
  const steps = [
    { n: 1, label: "클러스터 연결" },
    { n: 2, label: "데이터 인입" },
    { n: 3, label: "비교 조건" },
    { n: 4, label: "실행" },
  ];
  return (
    <ol className="mb-6 flex items-center justify-between">
      {steps.map((s, i) => (
        <li key={s.n} className="flex-1 flex items-center">
          <div
            className={
              "flex items-center gap-2 " +
              (s.n === current ? "text-brand-700 font-semibold"
               : s.n < current ? "text-gray-500" : "text-gray-400")
            }
          >
            <span
              className={
                "inline-flex h-6 w-6 items-center justify-center rounded-full text-xs " +
                (s.n === current ? "bg-brand-600 text-white"
                 : s.n < current ? "bg-emerald-500 text-white" : "bg-gray-200 text-gray-600")
              }
            >
              {s.n}
            </span>
            <span className="text-sm">{s.label}</span>
          </div>
          {i < steps.length - 1 && (
            <div className={"flex-1 h-px mx-3 " + (s.n < current ? "bg-emerald-400" : "bg-gray-200")} />
          )}
        </li>
      ))}
    </ol>
  );
}
