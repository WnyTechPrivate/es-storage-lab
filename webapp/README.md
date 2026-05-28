# ES Storage Lab — webapp

`scripts/01~05` (파이프라인/템플릿 등록 → baseline 인입 → reindex × N → 측정 → 리포트) 를
UI 위저드로 추상화한 도구. 클러스터 자격증명을 동적으로 받아 여러 클러스터에 적용 가능하고,
SQLite 로 run 메타·측정값을 누적 보관해 과거/현재 결과를 비교한다.

요구사항 정의: [`../UI_요구사항.md`](../UI_요구사항.md)

---

## 폴더 구조

```
webapp/
├── backend/                          FastAPI + uvicorn (8765)
│   ├── .venv/                        Python 3.13 (Anaconda) 격리
│   ├── requirements.txt
│   └── app/
│       ├── main.py                   FastAPI 엔트리, CORS, static 서빙
│       ├── paths.py                  R&D/ 폴더 기준 경로 해석
│       ├── schemas.py                pydantic 요청/응답
│       ├── adapters/
│       │   ├── es_client.py          호스트/유저/패스 동적, verify_certs=false
│       │   ├── cases.py              case_name, basic_24(dataset), expand
│       │   └── templates.py          composed_of: ecs@mappings, 단일 매핑
│       ├── services/
│       │   ├── generator.py          firewall (Fortinet) 합성 로그
│       │   ├── web_generator.py      web access/req/error 70/25/5 + agent 메타
│       │   ├── snmp_generator.py     snmp 12-field positional, 7 장비 60초 폴링 시뮬레이션
│       │   ├── setup.py              ecs@mappings 체크 + pipelines + templates
│       │   ├── ingest.py             bulk + async force_merge (text-line / ndjson)
│       │   ├── reindex.py            baseline → case, async poll
│       │   ├── measure.py            _refresh + 400ms + _disk_usage
│       │   ├── cleanup.py            ds + template + pipeline 삭제
│       │   ├── runner.py             백그라운드 워커, 직렬 큐
│       │   └── events.py             Lock + deque, SSE 폴링용
│       ├── db/store.py               SQLite (runs, measurements, cascade)
│       └── routes/
│           ├── cluster.py            /test, /datastreams, /datastreams/delete
│           └── runs.py               CRUD + events SSE + remeasure
└── frontend/                         Vite + React 19 + TS + Tailwind v3
    └── src/
        ├── pages/
        │   ├── Wizard.tsx            4-step
        │   ├── Reports.tsx           목록 + 삭제 모달, 3초 폴링
        │   ├── RunDetail.tsx         차트 + 표 + 영향 랭킹 + 다시 측정
        │   └── Cleanup.tsx           고정 5 패턴 ds 조회/삭제
        ├── components/Step{1,2,3,4}*.tsx
        ├── ui/                       Button / Input / Card / Progress / Badge
        ├── lib/{api,format,types}.ts
        └── App.tsx
```

---

## 실행

### 백엔드 (8765)

```powershell
cd "C:\Users\limsw\OneDrive\Desktop\업무\R&D\webapp\backend"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8765 --reload --reload-dir app
```

### 프론트 dev (5173 — `/api/*` 프록시)

```powershell
cd "C:\Users\limsw\OneDrive\Desktop\업무\R&D\webapp\frontend"
$env:Path += ";C:\Program Files\nodejs"
npm run dev
```

브라우저: <http://localhost:5173>

> `R&D` 폴더 이름의 `&` 때문에 npm 의 `.bin` shim 이 깨집니다.
> `package.json` 의 scripts 는 `node node_modules/<tool>/bin/...` 직접 호출로 우회되어 있습니다.

### 프로덕션 단일 포트

```powershell
cd "C:\Users\limsw\OneDrive\Desktop\업무\R&D\webapp\frontend"
npm run build      # → frontend/dist
cd ..\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8765
# dist 가 / 경로에서 자동 서빙됨
```

---

## 화면

### `/` — New run 위저드 (4-step)

| Step | 내용 |
|---|---|
| 1. 클러스터 연결 | host/user/password → `POST /api/cluster/test`. 버전·라이선스 자동 감지, ZSTD/synthetic 가용성 배지. TLS 검증은 끔 |
| 2. 데이터 인입 | **데이터 소스 라디오 (firewall / web)** + 목표 용량 (10 MB / 100 MB / 500 MB / 1 GB 프리셋 또는 임의). seed 는 고정·UI 비노출 |
| 3. 비교 조건 | **24 케이스 매트릭스**: Index mode × Source mode × Codec × Parsing. event.original 의 idx/dv 는 항상 false (안내 박스) |
| 4. 실행 진행률 | SSE + 2초 status 폴링 fallback. generate% / ingest% / 케이스별 reindex% / force_merge / 완료 케이스 칩 |

완료/실패 자동 감지 → Run detail 화면으로 이동.

### `/reports` — 누적 run 목록

- 3 초 폴링으로 자동 새로고침
- 컬럼: 시각 / 라벨 / **데이터셋 배지** / 상태 / 클러스터 / cases / raw size / raw docs / 🗑
- `done` / `failed` 상태만 삭제 가능 (`queued` / `running` 은 비활성)

### `/report/:id` — Run detail

- 상단: `← Runs` · **다시 측정** 버튼 · status badge
- **Run 카드**: 시각·데이터셋 배지·클러스터·case 수·raw input
- **저장 크기** 차트: Y축 절대 크기, 균등 6 tick, **원본 크기 굵은 점선** 오버레이. raw 미만 초록·초과 빨강
- **케이스 표**: 가운데 정렬, 풀어쓰기 라벨 (logsdb / standard / synthetic / stored / ZSTD / LZ4 / event.original-only / event.original + parsed / parsed-only). 정렬 가능 컬럼 (Datastream / Store size / 원본 대비 증감율). 마지막 컬럼은 `±X%` 색 표기 (음수 초록 · 양수 빨강)
- **어떤 설정이 저장 공간을 가장 크게 바꾸는가**: 카드 리스트. 순위 / 격차 / 각 선택의 평균 결과 (+→− 정렬). 동일 패턴 축이 있으면 (예: confounding) 노란 박스로 자동 안내
- 3 초 폴링 — 상태 terminal 되면 폴링 중단

**다시 측정**: reindex 없이 클러스터의 기존 ds 들에 대해 측정만 재실행. 모달에서 user/password 입력 → `POST /api/runs/{id}/remeasure` → DB 의 measurements 갱신 + UI 자동 새로고침.

### `/cleanup` — 클러스터 ds 정리

- 클러스터 입력 → "조회" → **고정 4 패턴**으로 ds 조회 (모든 namespace 자동 매치):
  - `logs-ldb*-*` — 모든 logsdb 케이스 (default / service / snmp / ...)
  - `logs-std*-*` — 모든 standard 케이스
  - `logs-tsds*-*` — 모든 TSDS 케이스
  - `logs-baseline-*` — 모든 namespace 의 baseline
- 표에서 체크박스로 선택 → "선택 항목 삭제" → 확인 모달
- pipeline / index template 은 절대 건드리지 않음
- 백엔드 가드: 모든 패턴/이름은 `logs-` 로 시작해야 하고, 와일드카드 in-the-middle 금지

---

## API 요약

| 메서드 | 경로 | 비고 |
|---|---|---|
| POST | `/api/cluster/test` | 버전 / 라이선스 / ZSTD·synthetic 가용성 |
| POST | `/api/cluster/datastreams` | 고정 5 패턴 ds 조회 |
| POST | `/api/cluster/datastreams/delete` | 항목별 결과 반환, prefix 가드 |
| POST | `/api/runs` | run 시작 (`{cluster, ingest, cases, label?}`) |
| GET  | `/api/runs` | 목록 |
| GET  | `/api/runs/{id}` | 메타 |
| GET  | `/api/runs/{id}/measurements` | 측정 row |
| GET  | `/api/runs/{id}/events` | SSE 진행률 |
| POST | `/api/runs/{id}/remeasure` | reindex 없이 측정만 재실행 |
| DELETE | `/api/runs/{id}` | DB cascade 삭제 (queued/running 거부) |
| GET  | `/api/runs/current` | 현재 진행중 run id |

---

## 핵심 설계 결정

### 명명 규칙

```
case        = {mode}.{src}.{codec}.{idx}.{dv}.{parsing}
datastream  = logs-{case}-{namespace}
예          = logs-ldb.syn.zstd.if.df.p3-default
              logs-ldb.syn.zstd.if.df.p3-service
              logs-tsds.syn.zstd.if.df.p3-snmp
```

- mode: `std` / `ldb` / `tsds` (time_series — TSDS)
- src: `str` (stored) / `syn` (synthetic)
- codec: `lz4` (default) / `zstd` (best_compression, ES 8.19+ → ZSTD)
- idx / dv: 항상 `if` / `df` (event.original 의 index/doc_values 가 false)
- parsing: `p1` (event.original-only) / `p2` (event.original + parsed) / `p3` (parsed-only)
- namespace: `default` (firewall) / `service` (web)

UI 셀에서는 풀어쓴 라벨, datastream 명은 원본 토큰 그대로 표시.

### 데이터셋

| dataset | namespace | baseline ds | pipeline triplet | 특성 |
|---|---|---|---|---|
| `firewall` | `default` | `logs-baseline-default` | `raw_ingest` / `parsing2_full` / `parsing3_parsed_only` | Fortinet KV syslog · avg msg ≈ 620 B |
| `web` | `service` | `logs-baseline-service` | `raw_ingest_service` / `parsing2_full_service` / `parsing3_parsed_only_service` | access / req / error 70-25-5 혼합 · avg msg ≈ 245 B · Agent 메타 동봉 |
| `snmp` | `snmp` | `logs-baseline-snmp` | `raw_ingest_snmp` / `parsing2_full_snmp` / `parsing3_parsed_only_snmp` | 12-field positional pipe log · 7 장비 60초 폴링 (interface/system/env/trap 자동 혼합) · avg msg ≈ 55 B · Agent 메타 동봉 |

매트릭스 자체 (24 케이스, 매핑 정책) 는 모든 dataset 이 동일. 데이터셋 추가 절차는 [UI_요구사항.md](../UI_요구사항.md) 참조.

### `raw_size_bytes` 의 의미 — message-only

두 dataset 의 비교 공정성을 위해, 두 generator 모두 **메시지 텍스트 누적량** 이 target 에 도달할 때까지 생성하고 그 값을 `raw_size_bytes` 로 기록한다.

- firewall: NDJSON 인코딩 없이 한 줄 텍스트 = message. 파일 = message 합계.
- web: NDJSON 한 줄 = message + 메타. **메시지 합계가 target 일 때까지** 생성. 결과 NDJSON 파일은 더 크지만 (메타 분량 포함), `raw_size_bytes` 에는 message-only 양이 기록됨.

→ 같은 "10 MB" 가 두 dataset 에서 동일 의미.

### Index template — 단일 매핑 패턴

```json
{
  "composed_of": ["ecs@mappings"],
  "template": {
    "settings": {
      "index": {
        "mode": "logsdb|standard",
        "mapping.source.mode": "synthetic|stored",
        "codec": "best_compression|default",
        "default_pipeline": "<dataset-specific p2|p3>"
      }
    },
    "mappings": {
      "properties": {
        "@timestamp": {"type": "date"},
        "event": {"properties": {"original": {
          "type": "keyword", "ignore_above": 8192,
          "index": false, "doc_values": false
        }}}
      }
    }
  }
}
```

- `event.original` 의 index/doc_values 는 ECS 기본대로 false. `ignore_above` 만 8192 로 명시 override (ECS 기본 1024 → 8192)
- 메시지가 8192 byte 를 초과하면:
  - stored _source: `_source` 그대로 저장 (매핑은 어차피 무관)
  - **synthetic _source**: 매핑으로 재구성 불가 → `_ignored_source` 로 fallback. `measurements.ignored_source_b` 가 의미 있는 값이 됨
- 그 외 필드는 ECS@mappings 가 처리. `dynamic_templates` / 직접 properties 매핑 모두 제거

baseline 도 dataset 별 1개씩. `composed_of: ["ecs@mappings"]` + stored _source + 해당 raw_ingest pipeline.

### setup 사전 점검

`GET /_component_template/ecs@mappings` 가 200 이 아니면 명확한 한국어 오류 후 거부.
ES 8.x+ stack templates 가 활성화된 클러스터 가정.

### TB 대비 — async task

`_reindex` 와 `_forcemerge` 모두 `wait_for_completion=false` → `_tasks/{id}` 폴링.
HTTP 타임아웃 위험 제거. reindex 의 경우 `created/total` 이 status 에 있어 진행률에 사용.

### 측정 안정화

`measure_one` 진입 시 해당 ds 에 `_refresh` 한 번 더 + 400 ms sleep.
force_merge 응답 직후 Lucene 의 post-merge 정리로 store size 가 잠깐 흔들리는 stale 을 방지.
그래도 어긋난 측정이 들어가면 Run detail 의 **다시 측정** 으로 보정.

### SSE 진행률

`asyncio.Queue` 가 thread-safe 가 아니라 워커 스레드 → SSE 라우트 wakeup 이 깨지는 버그가 있어 폴링 기반으로 재설계:
- 워커는 `Lock` 보호 `deque` 에 이벤트 append 만
- SSE 핸들러는 cursor 들고 250 ms 간격으로 snapshot 후 yield
- 보강: 프론트가 별도로 2 초마다 `GET /api/runs/{id}` status 폴링

### Cleanup 안전 가드

- 조회 패턴은 백엔드 하드코딩 5 개 — UI 는 정보 표시만, 임의 입력 불가
- 삭제 요청 각 이름이 `logs-` 로 시작 + 와일드카드 미포함 일 때만 처리
- pipeline · index template 은 어떤 경우에도 삭제하지 않음

---

## DB 스키마 (SQLite, `webapp/backend/app/db/store.sqlite`)

```sql
CREATE TABLE runs (
  id              TEXT PRIMARY KEY,
  label           TEXT,
  created_at      REAL NOT NULL,
  finished_at     REAL,
  status          TEXT NOT NULL,   -- queued | running | done | failed | cancelled
  cluster_host    TEXT,
  cluster_version TEXT,
  cluster_license TEXT,
  ingest_mode     TEXT,            -- 'generated' | 'path'
  dataset         TEXT,            -- 'firewall' | 'web'
  raw_size_bytes  INTEGER,         -- message-only bytes
  raw_docs        INTEGER,
  cases_json      TEXT,
  error           TEXT
);

CREATE TABLE measurements (
  run_id            TEXT NOT NULL,
  case_name         TEXT NOT NULL,
  datastream        TEXT,
  backing_index     TEXT,
  docs              INTEGER,
  raw_bytes         INTEGER,
  pri_store_bytes   INTEGER,
  ratio_pri_over_raw REAL,
  inverted_index_b  INTEGER,
  doc_values_b      INTEGER,
  stored_fields_b   INTEGER,
  points_b          INTEGER,
  norms_b           INTEGER,
  term_vectors_b    INTEGER,
  knn_vectors_b     INTEGER,
  ignored_source_b  INTEGER,
  PRIMARY KEY (run_id, case_name),
  FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);
```

`init_db()` 가 idempotent — 기존 DB 에 `dataset` 컬럼이 없으면 ALTER TABLE 로 추가.

---

## 미구현 (다음 마일스톤 후보)

- 옵션 ② 서버 경로 인입 (현재는 합성 로그만)
- run 간 diff
- 결과 CSV / HTML 다운로드 버튼
- 동시 다중 run (현재는 단일 worker 직렬)
- 케이스 간 병렬 reindex (concurrency 토글)
- 실패 케이스 재시도
