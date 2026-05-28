import { useState } from "react";
import type { Dataset, IngestGenerated } from "../lib/types";
import { Card } from "../ui/Card";
import { Button } from "../ui/Button";
import { Field, Input } from "../ui/Input";

type Props = {
  initial: IngestGenerated;
  onBack: () => void;
  onConfirmed: (ingest: IngestGenerated) => void;
};

const PRESETS: { label: string; bytes: number }[] = [
  { label: "10 MB",  bytes: 10 * 1024 * 1024 },
  { label: "100 MB", bytes: 100 * 1024 * 1024 },
  { label: "500 MB", bytes: 500 * 1024 * 1024 },
  { label: "1 GB",   bytes: 1024 * 1024 * 1024 },
];

const DATASETS: { value: Dataset; title: string; desc: string; namespace: string }[] = [
  {
    value: "firewall",
    title: "방화벽 (Fortinet traffic)",
    desc: "단일 KV 형식 syslog. 한 줄 = 한 이벤트.",
    namespace: "logs-{case}-default",
  },
  {
    value: "web",
    title: "Web (access · request · error)",
    desc: "Nginx-like 3 타입 혼합 (access 70%, request 25%, error 5%) + Elastic Agent 메타 (host / agent / log).",
    namespace: "logs-{case}-service",
  },
  {
    value: "snmp",
    title: "SNMP positional log",
    desc: "12 개 숫자 코드 + 값을 pipe 로 잇는 압축 포맷. 7 장비 (Cisco/Juniper/Fortinet/Arista) 60초 폴링 시뮬레이션 — interface / system / env / trap 자동 혼합.",
    namespace: "logs-{case}-snmp",
  },
];

export function Step2Ingest({ initial, onBack, onConfirmed }: Props) {
  const [dataset, setDataset] = useState<Dataset>(initial.dataset);
  const [bytes, setBytes] = useState<number>(initial.target_bytes);
  const seed = initial.seed;

  function approxDocs(b: number) {
    // message-only bytes per doc (matches the generator's stop condition)
    const avgMsgBytes =
      dataset === "firewall" ? 620 :
      dataset === "web"      ? 245 :
      /* snmp */               55;
    return Math.round(b / avgMsgBytes);
  }

  return (
    <Card
      title={<span>Step 2 · 데이터 인입</span>}
      footer={
        <>
          <Button variant="ghost" onClick={onBack}>← 이전</Button>
          <Button
            disabled={bytes < 1024}
            onClick={() =>
              onConfirmed({ mode: "generated", dataset, target_bytes: bytes, seed })
            }
          >
            다음 →
          </Button>
        </>
      }
    >
      <Field label="데이터 소스">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {DATASETS.map((d) => {
            const on = dataset === d.value;
            return (
              <button
                key={d.value}
                type="button"
                onClick={() => setDataset(d.value)}
                className={
                  "text-left rounded-lg border px-4 py-3 transition-colors " +
                  (on
                    ? "border-brand-600 bg-brand-50 ring-1 ring-brand-500"
                    : "border-gray-300 bg-white hover:bg-gray-50")
                }
              >
                <div className="flex items-center gap-2">
                  <span className={"inline-block h-4 w-4 rounded-full border-2 " +
                    (on ? "border-brand-600 bg-brand-600" : "border-gray-300 bg-white")}/>
                  <span className="font-medium text-sm text-gray-900">{d.title}</span>
                </div>
                <div className="mt-2 text-xs text-gray-600">{d.desc}</div>
                <div className="mt-2 text-[11px] text-gray-500">
                  data stream: <code>{d.namespace}</code>
                </div>
              </button>
            );
          })}
        </div>
      </Field>

      <Field label="목표 용량">
        <div className="flex flex-wrap gap-2 mb-2">
          {PRESETS.map((p) => (
            <Button
              key={p.label}
              variant={bytes === p.bytes ? "primary" : "secondary"}
              onClick={() => setBytes(p.bytes)}
            >
              {p.label}
            </Button>
          ))}
        </div>
        <Input
          type="number"
          min={1024}
          value={bytes}
          onChange={(e) => setBytes(parseInt(e.target.value || "0", 10) || 0)}
        />
        <div className="text-xs text-gray-500 mt-1">
          ≈ {(bytes / 1024 / 1024).toFixed(2)} MB · 예상 약 {approxDocs(bytes).toLocaleString()} docs
          <span className="ml-2 text-gray-400">
            (메시지 텍스트 누적량 기준 — web 은 agent 메타 별도로 추가됨)
          </span>
        </div>
      </Field>
    </Card>
  );
}
