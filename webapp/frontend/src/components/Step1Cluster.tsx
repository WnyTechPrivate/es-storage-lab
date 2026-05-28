import { useState } from "react";
import { api } from "../lib/api";
import type { ClusterCreds, ClusterTestResponse } from "../lib/types";
import { Card } from "../ui/Card";
import { Button } from "../ui/Button";
import { Field, Input } from "../ui/Input";
import { Badge } from "../ui/Badge";

type Props = {
  initial: ClusterCreds;
  onConfirmed: (creds: ClusterCreds, test: ClusterTestResponse) => void;
};

export function Step1Cluster({ initial, onConfirmed }: Props) {
  const [creds, setCreds] = useState<ClusterCreds>(initial);
  const [busy, setBusy] = useState(false);
  const [test, setTest] = useState<ClusterTestResponse | null>(null);

  async function runTest() {
    setBusy(true);
    setTest(null);
    try {
      const r = await api.testCluster(creds);
      setTest(r);
    } catch (e) {
      setTest({ ok: false, error: String(e) });
    } finally {
      setBusy(false);
    }
  }

  function next() {
    if (test?.ok) onConfirmed(creds, test);
  }

  return (
    <Card
      title={<span>Step 1 · Elasticsearch 클러스터 연결</span>}
      footer={
        <>
          <Button variant="secondary" disabled={busy} onClick={runTest}>
            {busy ? "테스트 중…" : "연결 테스트"}
          </Button>
          <Button disabled={!test?.ok} onClick={next}>
            다음 →
          </Button>
        </>
      }
    >
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <Field label="Host (URL)" hint="https://10.10.10.20:9200">
          <Input
            value={creds.host}
            placeholder="https://host:9200"
            onChange={(e) => setCreds({ ...creds, host: e.target.value })}
          />
        </Field>
        <Field label="Username">
          <Input
            value={creds.user}
            onChange={(e) => setCreds({ ...creds, user: e.target.value })}
          />
        </Field>
        <Field label="Password">
          <Input
            type="password"
            value={creds.password}
            onChange={(e) => setCreds({ ...creds, password: e.target.value })}
          />
        </Field>
      </div>
      <div className="flex items-center gap-2 text-xs text-gray-500">
        <Badge tone="warn">TLS 검증 비활성</Badge>
        자체 서명 인증서 / 인증서 검증 오류 무시 (verify_certs=false)
      </div>

      {test && (
        <div className="mt-5">
          {test.ok ? (
            <div className="rounded-md bg-emerald-50 border border-emerald-200 p-3 text-sm">
              <div className="font-semibold text-emerald-700 mb-1">연결 성공</div>
              <div className="grid grid-cols-2 md:grid-cols-3 gap-y-1 gap-x-4 text-gray-700">
                <div>cluster: <code>{test.cluster_name}</code></div>
                <div>node: <code>{test.name}</code></div>
                <div>version: <code>{test.version}</code></div>
                <div>lucene: <code>{test.lucene_version}</code></div>
                <div>license: <code>{test.license_type ?? "?"}</code> ({test.license_status ?? "?"})</div>
              </div>
              <div className="mt-2 flex flex-wrap gap-2">
                {test.synthetic_source_supported === false && (
                  <Badge tone="warn">
                    Basic 라이선스 → synthetic _source 가 stored 로 fallback 됨
                  </Badge>
                )}
                {test.zstd_codec_supported === false && (
                  <Badge tone="warn">
                    ES {test.version} → best_compression 은 DEFLATE (8.19+ 부터 ZSTD)
                  </Badge>
                )}
                {test.zstd_codec_supported && (
                  <Badge tone="info">best_compression = ZSTD</Badge>
                )}
                {test.synthetic_source_supported && (
                  <Badge tone="info">synthetic _source 사용 가능</Badge>
                )}
              </div>
            </div>
          ) : (
            <div className="rounded-md bg-red-50 border border-red-200 p-3 text-sm">
              <div className="font-semibold text-red-700 mb-1">연결 실패</div>
              <div className="text-red-700 whitespace-pre-wrap break-all">{test.error}</div>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}
