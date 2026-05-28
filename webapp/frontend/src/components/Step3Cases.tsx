import { useMemo, useState } from "react";
import type { CaseAxes } from "../lib/types";
import { Card } from "../ui/Card";
import { Button } from "../ui/Button";
import { Field, Input } from "../ui/Input";
import { Badge } from "../ui/Badge";

type Props = {
  initial: CaseAxes;
  initialLabel?: string;
  onBack: () => void;
  onConfirmed: (axes: CaseAxes, label?: string) => void;
};

type Axis<T extends string> = { value: T; label: string; hint?: string };

const AX = {
  mode: [
    { value: "std",  label: "standard" },
    { value: "ldb",  label: "logsdb" },
    { value: "tsds", label: "TSDS", hint: "time_series" },
  ] as Axis<"std" | "ldb" | "tsds">[],
  source: [
    { value: "str", label: "stored" },
    { value: "syn", label: "synthetic" },
  ] as Axis<"str" | "syn">[],
  codec: [
    { value: "lz4", label: "LZ4", hint: "default" },
    { value: "zstd", label: "ZSTD", hint: "best_compression · 8.19+" },
  ] as Axis<"lz4" | "zstd">[],
  parsing: [
    { value: "p1", label: "event.original-only" },
    { value: "p2", label: "event.original + parsed" },
    { value: "p3", label: "parsed-only" },
  ] as Axis<"p1" | "p2" | "p3">[],
};

function ChipGroup<T extends string>({
  label, options, value, onChange,
}: {
  label: string;
  options: Axis<T>[];
  value: T[];
  onChange: (v: T[]) => void;
}) {
  function toggle(v: T) {
    onChange(value.includes(v) ? value.filter((x) => x !== v) : [...value, v]);
  }
  return (
    <div>
      <div className="text-xs font-medium text-gray-700 mb-1">{label}</div>
      <div className="flex flex-wrap gap-2">
        {options.map((o) => {
          const on = value.includes(o.value);
          return (
            <button
              key={o.value}
              type="button"
              onClick={() => toggle(o.value)}
              className={
                "rounded-md border px-3 py-1.5 text-xs transition-colors " +
                (on
                  ? "bg-brand-600 border-brand-600 text-white"
                  : "bg-white border-gray-300 text-gray-700 hover:bg-gray-50")
              }
              title={o.hint}
            >
              <span>{o.label}</span>
              {o.hint && (
                <span className={"ml-1 " + (on ? "text-brand-100" : "text-gray-400")}>· {o.hint}</span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function Step3Cases({ initial, initialLabel, onBack, onConfirmed }: Props) {
  const [axes, setAxes] = useState<CaseAxes>(initial);
  const [label, setLabel] = useState<string>(initialLabel || "");

  const caseCount = useMemo(() => {
    return axes.modes.length * axes.sources.length *
      axes.codecs.length * axes.parsings.length;
  }, [axes]);

  const empty =
    axes.modes.length === 0 || axes.sources.length === 0 ||
    axes.codecs.length === 0 || axes.parsings.length === 0;
  const tooMany = caseCount > 64;

  return (
    <Card
      title={<span>Step 3 · 비교 조건</span>}
      footer={
        <>
          <Button variant="ghost" onClick={onBack}>← 이전</Button>
          <Button
            disabled={empty || tooMany}
            onClick={() => onConfirmed(axes, label.trim() || undefined)}
          >
            실행 →
          </Button>
        </>
      }
    >
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-5">
        <ChipGroup label="Index mode" options={AX.mode} value={axes.modes}
          onChange={(v) => setAxes({ ...axes, modes: v })} />
        <ChipGroup label="Source mode (_source)" options={AX.source} value={axes.sources}
          onChange={(v) => setAxes({ ...axes, sources: v })} />
        <ChipGroup label="Codec" options={AX.codec} value={axes.codecs}
          onChange={(v) => setAxes({ ...axes, codecs: v })} />
        <ChipGroup label="Parsing" options={AX.parsing} value={axes.parsings}
          onChange={(v) => setAxes({ ...axes, parsings: v })} />
      </div>

      <div className="mb-5 rounded-lg bg-blue-50 border border-blue-200 px-4 py-3 text-xs text-blue-900 space-y-1">
        <div><b className="font-semibold">event.original 매핑</b> — 모든 케이스에서 <code>index</code> / <code>doc_values</code> 가
        <b> false</b> (ECS 기본). 그 외 필드는 ECS@mappings 표준에 일임.</div>
        <div><b className="font-semibold">TSDS</b> — <code>index.mode=time_series</code>, dataset 별 dimension 자동 적용
        (firewall: source/destination.ip · web: host/service.name · snmp: observer.id_num + snmp.metric_code).
        <code>p1</code> 은 parsed 필드가 없어 routing_path 불충족 → 인덱싱 실패 가능.</div>
      </div>

      <Field label="라벨 (선택)" hint="Report 에서 이 run 을 식별하기 위한 메모">
        <Input
          value={label}
          placeholder="예: 2026-05-14 ECS 매트릭스 24 케이스"
          onChange={(e) => setLabel(e.target.value)}
        />
      </Field>

      <div className="flex items-center justify-between rounded-lg border border-gray-200 bg-white p-3">
        <div className="text-sm">
          총 <span className="font-semibold tabular-nums">{caseCount}</span>개 케이스가 생성됩니다.
        </div>
        <div className="flex gap-2">
          {empty && <Badge tone="danger">각 축에서 1개 이상 선택하세요</Badge>}
          {tooMany && <Badge tone="warn">48 개 초과 — 시간이 매우 오래 걸릴 수 있습니다</Badge>}
          {!empty && !tooMany && <Badge tone="success">실행 가능</Badge>}
        </div>
      </div>
    </Card>
  );
}
