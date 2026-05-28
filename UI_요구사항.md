# ES 저장효율 비교 UI 요구사항

작성: 2026-05-13 / 최종 갱신: 2026-05-14
대상: 위앤유텍 ES 저장효율 R&D 도구 (`webapp/`).

`scripts/01~05` CLI 흐름을 UI 위저드로 추상화. 클러스터 자격증명을 동적으로 받아 여러 클러스터를 같은 워크스테이션에서 굴릴 수 있고, SQLite 로 run 메타·측정값을 누적 보관해 과거/현재 결과를 비교한다.

---

## 1. 화면 흐름

```
[Step 1. 클러스터 연결]
        ↓
[Step 2. 데이터 인입]   — 데이터 소스 (firewall / web) + 목표 용량
        ↓
[Step 3. 비교 조건]     — 24 케이스 (mode × src × codec × parsing)
        ↓
[Step 4. 실행 + 진행률]  — SSE + status 폴링
        ↓
[Reports] → [Run detail] → 다시 측정 / 삭제
[Cleanup]                — 클러스터 ds 청소
```

---

## 2. 비교 매트릭스

### 2.1 case 토큰 (점 구분)

```
case        = {mode}.{src}.{codec}.{idx}.{dv}.{parsing}
datastream  = logs-{case}-{namespace}
```

- `mode`    ∈ `std` (standard) / `ldb` (logsdb) / `tsds` (time_series — TSDS)
- `src`     ∈ `str` (stored) / `syn` (synthetic)
- `codec`   ∈ `lz4` (default) / `zstd` (best_compression — ES 8.19+ 부터 ZSTD)
- `idx`     = `if` 고정 — event.original `index=false`
- `dv`      = `df` 고정 — event.original `doc_values=false`
- `parsing` ∈ `p1` (event.original-only) / `p2` (event.original + parsed) / `p3` (parsed-only)

→ **36 케이스** = 3 × 2 × 2 × 3.

TSDS 케이스는 `index.mode=time_series` + dataset 별 `routing_path` + dimension/metric 매핑이 적용됨:
- firewall: routing_path = `source.ip + destination.ip`
- web: routing_path = `host.name + service.name`
- snmp: routing_path = `observer.id_num + snmp.metric_code`, `snmp.value` 는 gauge metric

dimension 매핑은 std/ldb/tsds 모든 mode 의 case template 에 동일하게 들어가서 비교 공정성 유지 (TSDS 모드 외에는 `time_series_dimension/metric` 속성이 무시됨).
TSDS template 의 `look_back_time` / `look_ahead_time` = 30d 로 generator timestamp 폭에 여유.

idx/dv 토큰은 6-token 명명 호환을 위해 유지하지만 토글하지 않는다.

### 2.2 데이터 소스 (Step 2 라디오 선택)

| dataset | namespace | 형식 |
|---|---|---|
| `firewall` (Fortinet traffic) | `logs-{case}-default` | KV syslog 한 줄 = 한 이벤트 |
| `web` (access / request / error) | `logs-{case}-service` | nginx-like 3 타입을 **70 / 25 / 5** 비율로 혼합. Elastic Agent 메타 동봉 |
| `snmp` (positional) | `logs-{case}-snmp` | 12 개 숫자 코드+값을 pipe 로 잇는 압축 포맷. 7 장비 60초 폴링 — interface (110) / system (120) / env (130) / trap (210) 자동 혼합. avg 55 B/line |

- 모든 dataset 이 24 케이스 매트릭스 + 매핑 정책 동일 (ECS@mappings 기반).
- 차이는 (1) namespace, (2) baseline ds, (3) ingest pipeline triplet.
- **새 dataset 추가 절차**: `services/<X>_generator.py` 작성 → `pipelines/raw_ingest_X.json` + `parsing2_full_X.json` + `parsing3_parsed_only_X.json` 작성 → `adapters/cases.py` 의 `DATASET_NAMESPACE` 에 매핑 추가 → `adapters/templates.py` 의 `DATASET_PIPELINES` 추가 → `services/setup.py` 의 `PIPELINES_BY_DATASET` 추가 → `services/runner.py` 의 `_GENERATORS` / `_RAW_FILENAMES` / `NDJSON_DATASETS` 추가 → `schemas.py` 의 dataset Literal 확장 → 프론트 `lib/types.ts`, `Step2Ingest.tsx`, `Reports/RunDetail` 배지 확장.
- Cleanup 패턴은 namespace 와 무관하게 `logs-ldb*-*` / `logs-std*-*` / `logs-baseline-*` 으로 자동 매치되므로 **패턴 수정 불필요**.

### 2.3 baseline

- `logs-baseline-default` / `logs-baseline-service` 가 reindex 의 source.
- 비교 표 / 차트의 분모에는 사용되지 않음 (자체 임시 저장소).

### 2.4 raw_size_bytes 의 의미

두 dataset 의 비교 공정성을 위해 **메시지 텍스트 양 기준** 으로 측정한다.

- firewall: 한 줄 텍스트 = message (NDJSON 인코딩 없음). 파일 크기 = message 합계.
- web: NDJSON 한 줄 = message + agent/host/log/ecs/data_stream. generator 가 **message 합계가 target 에 도달할 때까지** 생성. 그 결과 NDJSON 파일은 더 크지만(메타 분량 포함), `raw_size_bytes` 에는 message-only 양이 기록됨.

이렇게 통일하면 같은 "10 MB" target 이 두 dataset 에서 동일 의미를 가진다.

---

## 3. Step 별 상세

### 3.1 Step 1 — Elasticsearch 클러스터 연결

- Host (URL) / Username / Password
- "연결 테스트" → `POST /api/cluster/test`
  - 버전 / 라이선스(Basic·Trial·Enterprise) / Lucene 버전 자동 감지
  - 라이선스가 Basic 이면 "synthetic _source 가 stored 로 fallback" 경고
  - ES 8.19 미만이면 "ZSTD 미지원 — best_compression 은 DEFLATE" 경고
- TLS 검증은 항상 끔 (`verify_certs=false`)
- 비번은 메모리만 보관 (host / user 만 localStorage)

### 3.2 Step 2 — 데이터 인입

- **데이터 소스**: firewall / web 카드 라디오
- **목표 용량**: 10 MB / 100 MB / 500 MB / 1 GB 프리셋 또는 임의 값
- generator 가 합성 로그 파일 생성 → 해당 baseline ds 에 인입
- seed 는 코드 내부 고정 (UI 비노출, 재현성 보장)

### 3.3 Step 3 — 비교 조건

Basic 4 그룹만 노출 (Advanced 없음):

| 축 | 토큰 |
|---|---|
| Index mode | `standard` / `logsdb` |
| Source mode | `stored` / `synthetic` |
| Codec | `LZ4` / `ZSTD` |
| Parsing | `event.original-only` / `event.original + parsed` / `parsed-only` |

매핑 안내 박스로 명시: "event.original 의 index/doc_values 는 항상 false (ECS@mappings 기본). 그 외 필드 매핑은 ECS 표준에 일임."

라벨 (선택) 입력, 케이스 수 카운터, 64 케이스 초과 시 경고 배지.

### 3.4 Step 4 — 실행 + 진행률

- SSE 기반 진행률 (`/api/runs/{id}/events`) + 2 초 status 폴링 fallback
- 단계별 표시:
  - generate% (메시지 양 누적 vs target)
  - ingest% (baseline bulk send)
  - 케이스별 reindex% (`/_tasks` 폴링, created/total)
  - force_merge 진행 중 표시
  - 완료된 case 칩 누적
- 완료 시 자동으로 Run detail 로 이동

### 3.5 Index template 구조 (확정)

case template 공통:
- `composed_of: ["ecs@mappings"]`
- `settings.index.mode` = `standard` / `logsdb`
- `settings.index.mapping.source.mode` = `stored` / `synthetic`
- `settings.index.codec` = `default` / `best_compression`
- `settings.index.default_pipeline` (p2/p3 만)
  - firewall: `parsing2_full` / `parsing3_parsed_only`
  - web: `parsing2_full_service` / `parsing3_parsed_only_service`
- `mappings.properties` = `{"@timestamp": {"type": "date"}, "event.original": {"type": "keyword", "ignore_above": 8192, "index": false, "doc_values": false}}` (그 외 모든 필드는 ECS@mappings 가 처리)
- `event.original` 의 index/doc_values 는 ECS 기본대로 false. ignore_above 는 ECS 기본(1024) 대신 8192 로 override (다만 index/dv 가 둘 다 false 이므로 이번 매트릭스에서 ignore_above 트리거는 실효 없음 — 모든 doc 이 어차피 `_ignored_source` 로 폴백)

baseline 도 dataset 별로 1개씩 (`tpl-baseline-default` / `tpl-baseline-service`):
- `composed_of: ["ecs@mappings"]`, stored _source, default_pipeline 은 raw_ingest{_service}

`dynamic_templates`, 명시 properties 매핑, idx/dv 직접 토글 모두 폐기 — ECS@mappings 에 일임.

> 사전 점검: setup 단계에서 `GET /_component_template/ecs@mappings` 가 200 인지 확인. 없으면 명확한 한국어 오류로 거부.

### 3.6 Report 탭

#### 비교 기준 (중요)

- baseline 인덱스는 reindex 임시 저장소. 비교 대상 아님.
- 비교 분모 = **사용자가 Step 2 에서 지정한 메시지 양 (`raw_size_bytes`)**.
- 표 / 차트의 % 는 모두 "원본 대비 증감율 (%)" — `-X%` (절감, 초록) / `+X%` (증가, 빨강).

#### 핵심 표 컬럼

| 컬럼 | 표시 예 |
|---|---|
| Datastream | `logs-ldb.syn.zstd.if.df.p3-default` |
| Index mode | logsdb / standard |
| Source mode | synthetic / stored |
| Codec | LZ4 / ZSTD |
| Parsing | event.original-only / event.original + parsed / parsed-only |
| Store size | 2.93 MB |
| Docs | 17,944 |
| Size per doc | 171 B |
| 원본 대비 증감율 (%) | `-70.7%` (초록) / `+5.6%` (빨강) |

모든 셀 가운데 정렬. Datastream / Store size / 원본 대비 증감율은 정렬 가능.

#### 차트

- "저장 크기" 막대 차트 — Y축 절대 크기 (MB), 균등 6 tick
- raw input 만큼의 **굵은 점선** 오버레이 ("원본 X.XX MB")
- 막대 색: raw 미만 초록 / 초과 빨강

#### "어떤 설정이 저장 공간을 가장 크게 바꾸는가"

- 카드 리스트 형식. 각 축의 격차(spread)가 큰 순서로 정렬.
- 토큰별 평균 결과는 + → − 순. 색은 음수 초록 / 양수 빨강.
- 동일한 패턴으로 움직이는 두 축이 있으면 (예: 옛 mode-aware codec 같은 confounding) 자동 감지해서 노란 박스로 안내.

#### Reports 목록

- 시각 / 라벨 / 데이터셋(badge) / 상태 / 클러스터 / cases / raw size / raw docs
- 행마다 휴지통 (done/failed 만 활성)
- 3 초 폴링 자동 새로고침

#### 다시 측정

- Run detail 상단의 **다시 측정** 버튼 → `POST /api/runs/{id}/remeasure`
- reindex 없이 클러스터의 기존 ds 들에 대해 측정만 재실행
- 모달에 host(자동) + user + password 입력 → DB 의 measurements 가 덮어쓰기됨

---

## 4. Cleanup 페이지

클러스터의 ds 청소용 (별도 `/cleanup`).

조회 패턴은 백엔드 하드코딩 — 모든 namespace 를 자동 매치 (dataset 추가 시 패턴 수정 불필요):

```
logs-ldb*-*       # 모든 logsdb 케이스 (default/service/snmp/...)
logs-std*-*       # 모든 standard 케이스
logs-tsds*-*      # 모든 TSDS 케이스
logs-baseline-*   # 모든 namespace 의 baseline
```

- 패턴 입력은 UI 에 노출하지 않음 (안전 가드)
- 표 컬럼: 이름 / backing 수 / docs / store / template. store 크기 내림차순
- 체크박스 + "선택 항목 삭제" → 확인 모달
- **pipeline / index template 은 절대 건드리지 않음** (의도)
- 백엔드 가드 3 겹:
  1. 응답 ds 이름이 `logs-` 로 시작하지 않으면 표시 제외
  2. 삭제 요청 각 이름이 `logs-` 로 시작 + 와일드카드 미포함 일 때만 처리
  3. 패턴은 UI 가 보내지 않고 백엔드에서 고정

---

## 5. API 요약

| 메서드 | 경로 | 비고 |
|---|---|---|
| POST | `/api/cluster/test` | 버전 / 라이선스 / ZSTD·synthetic 가용성 |
| POST | `/api/cluster/datastreams` | 고정 5 패턴 ds 조회 (body 에 cluster creds) |
| POST | `/api/cluster/datastreams/delete` | 항목별 결과 반환, prefix 가드 |
| POST | `/api/runs` | run 시작 `{cluster, ingest, cases, label?}` |
| GET  | `/api/runs` | 목록 |
| GET  | `/api/runs/{id}` | 메타 |
| GET  | `/api/runs/{id}/measurements` | 측정 row |
| GET  | `/api/runs/{id}/events` | SSE 진행률 (cursor 폴링 기반) |
| POST | `/api/runs/{id}/remeasure` | reindex 없이 측정만 재실행 |
| DELETE | `/api/runs/{id}` | DB cascade 삭제 (queued/running 거부) |
| GET  | `/api/runs/current` | 현재 진행중 run id |

---

## 6. 비기능 / 운영 가정

- 동시 실행: 단일 워커 스레드 직렬 처리. 한 run 끝나야 다음 run.
- 비번 저장: 메모리 only (브라우저 새로고침 시 재입력)
- 클러스터 라이선스: Basic 이면 synthetic 이 stored 로 fallback (자동, 경고)
- TB 대비: `_reindex` / `_forcemerge` 모두 `wait_for_completion=false` + `_tasks` 폴링 — HTTP 타임아웃 위험 제거
- 측정 안정화: `measure_one` 진입 시 `_refresh` + 400 ms sleep (force_merge 직후 post-merge 정리로 인한 stale 방지)

---

## 7. 폴더 구조

```
R&D/
├── data/                                    raw_sample.log (legacy, scripts 용)
├── pipelines/
│   ├── raw_ingest.json                      firewall baseline
│   ├── parsing2_full.json
│   ├── parsing3_parsed_only.json
│   ├── raw_ingest_service.json              web baseline
│   ├── parsing2_full_service.json
│   ├── parsing3_parsed_only_service.json
│   ├── raw_ingest_snmp.json                 snmp baseline
│   ├── parsing2_full_snmp.json
│   └── parsing3_parsed_only_snmp.json
├── results/                                 legacy scripts 출력
├── scripts/                                 옛 CLI (보존, webapp 이 의존하지 않음)
├── UI_요구사항.md                            본 문서
└── webapp/
    ├── backend/    FastAPI + venv
    ├── frontend/   Vite + React + TS
    └── README.md   실행 안내
```

---

## 8. 미구현 (다음 마일스톤 후보)

- 옵션 ② 서버 경로 인입 (현재는 합성 로그만)
- run 간 diff
- CSV / HTML 다운로드 버튼
- 동시 다중 run (현재 단일 worker 직렬)
- 케이스 간 병렬 reindex (concurrency 토글)
- 실패 케이스 재시도
