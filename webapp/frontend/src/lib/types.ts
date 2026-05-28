export type ClusterCreds = {
  host: string;
  user: string;
  password: string;
};

export type ClusterTestResponse = {
  ok: boolean;
  error?: string;
  name?: string;
  cluster_name?: string;
  version?: string;
  lucene_version?: string;
  license_type?: string;
  license_status?: string;
  synthetic_source_supported?: boolean;
  zstd_codec_supported?: boolean;
};

export type Dataset = "firewall" | "web" | "snmp";

export type IngestGenerated = {
  mode: "generated";
  dataset: Dataset;
  target_bytes: number;
  seed: number;
};

export type IngestPath = {
  mode: "path";
  dataset: Dataset;
  path: string;
};

export type CaseAxes = {
  modes: ("std" | "ldb" | "tsds")[];
  sources: ("str" | "syn")[];
  codecs: ("lz4" | "zstd")[];
  parsings: ("p1" | "p2" | "p3")[];
};

export type StartRunRequest = {
  label?: string;
  cluster: ClusterCreds;
  ingest: IngestGenerated | IngestPath;
  cases: CaseAxes;
  cleanup_first: boolean;
};

export type StartRunResponse = {
  run_id: string;
  cases: string[];
  queued_position: number;
};

export type RunSummary = {
  id: string;
  label?: string;
  created_at: number;
  finished_at?: number;
  status: "queued" | "running" | "done" | "failed" | "cancelled";
  cluster_host?: string;
  ingest_mode?: "generated" | "path";
  dataset?: Dataset;
  raw_size_bytes?: number;
  raw_docs?: number;
  cases: string[];
};

export type MeasurementRow = {
  case_name: string;
  datastream?: string;
  backing_index?: string;
  docs?: number;
  raw_bytes?: number;
  pri_store_bytes?: number;
  ratio_pri_over_raw?: number;
  inverted_index_b?: number;
  doc_values_b?: number;
  stored_fields_b?: number;
  points_b?: number;
  norms_b?: number;
  term_vectors_b?: number;
  knn_vectors_b?: number;
  ignored_source_b?: number;
};

export type RunEvent = {
  t: number;
  kind: string;
  [k: string]: unknown;
};

export type DataStreamInfo = {
  name: string;
  backing_count: number;
  docs: number;
  store_bytes: number;
  generation?: number;
  template?: string;
};

export type DeleteResultItem = {
  name: string;
  deleted: boolean;
  error?: string;
};
