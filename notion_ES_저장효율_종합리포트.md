# Elasticsearch 저장 효율 비교 R&D — 종합 리포트

작성: 2026-05-18
대상 클러스터: ES 9.3.1, 4-node (192.168.200.71)

---

## 1. 요약 (TL;DR)

- ES 의 4 축 (Index mode / Source mode / Codec / Parsing) 이 저장 공간에 미치는 영향을 **실측**으로 정량화하는 도구를 제작.
- 3 개 dataset (firewall, web, snmp) × 24~36 케이스 매트릭스를 같은 클러스터에서 측정.
- 핵심 발견:
  1. **압축의 일꾼은 `index.codec` (ZSTD)**. mode 자체 (std/ldb)
  2. **logsdb 와 TSDS 의 진짜 차이는 doc_values 쪽**. logsdb 는 sort by time, TSDS 는 sort by _tsid → 시계열 dataset 에서 압축 폭발.
  3. **dataset 의 본질이 최적 조합을 결정**: 긴 텍스트 로그 (firewall) → `p1+ZSTD` 가 1위. 메트릭 시계열 (SNMP) → `TSDS + p3` 가 1위.

---

## 2. 배경

### 2.1 기존 R&D 환경의 한계

| 항목 | 기존 (`R&D/scripts/01~05.py`) | 한계 |
|---|---|---|
| 클러스터 변경 | 환경변수 + 코드 수정 | 매번 손이 감 |
| 매트릭스 변경 | `config.py` 수동 편집 | 비효율 |
| 진행률 확인 | stdout 만 봄 | 96 케이스 reindex 동안 진척 모름 |
| 결과 비교 | `report.html` 파일 직접 열기 | 다른 클러스터/일자 비교 어려움 |
| 다중 데이터셋 | 단일 (Fortinet 합성 로그만) | 다른 로그 타입 비교 불가 |

### 2.2 측정해야 할 축

ES 의 저장 효율을 좌우하는 4 가지 축:

```
index.mode        : standard / logsdb / time_series (TSDS)
mapping.source.mode: stored / synthetic
index.codec       : default(LZ4) / best_compression(ZSTD ≥ 8.19)
parsing 방식      : event.original-only / event.original+parsed / parsed-only
```

---

## 3. 목적

1. **사용자 누구나** 위저드 클릭으로 클러스터 인입 → 비교 → 리포트 확인.
2. **여러 클러스터 / 여러 dataset / 여러 매트릭스** 결과를 한 워크스테이션에 누적 보관.
3. ES 의 저장 메커니즘 (synthetic, _ignored_source, doc_values, codec) 의 **실제 동작을 실측 데이터로 검증**.
4. 운영 시 "어떤 데이터에 어떤 조합을 써야 하는가" 의 의사결정 근거 마련.

---

## 4. 시스템 구성

### 4.1 아키텍처

```
┌─────────────────────────────────────────────────────────┐
│  Browser (5173)                                         │
│  ┌──────────────┐ ┌────────────┐ ┌────────────┐         │
│  │ New run      │ │ Reports    │ │ Cleanup    │         │
│  │ (4-step      │ │ + RunDetail│ │            │         │
│  │  wizard)     │ │            │ │            │         │
│  └──────┬───────┘ └─────┬──────┘ └─────┬──────┘         │
│         │ /api/* (Vite proxy)          │                │
└─────────┼──────────────────────────────┼────────────────┘
          ▼                              ▼
┌──────────────────────────────────────────────────────────┐
│  FastAPI backend (8766)                                  │
│  ┌────────────────────────────────────────────────────┐  │
│  │ runner (background thread, 직렬 큐)                │  │
│  │   ├─ generator (firewall / web / snmp)             │  │
│  │   ├─ setup (pipelines + index templates)           │  │
│  │   ├─ ingest (bulk → baseline ds)                   │  │
│  │   ├─ reindex (baseline → case ds × N)              │  │
│  │   └─ measure (_disk_usage + _cat/indices)          │  │
│  └────────────────────────────────────────────────────┘  │
│  ┌────────────────────────┐  ┌────────────────────────┐  │
│  │ SSE event bus          │  │ SQLite store           │  │
│  │ (polling-based)        │  │ (runs + measurements)  │  │
│  └────────────────────────┘  └────────────────────────┘  │
└──────────────┬───────────────────────────────────────────┘
               │ REST + dynamic creds (verify_certs=false)
               ▼
┌──────────────────────────────────────────────────────────┐
│  Elasticsearch cluster (ES 9.3.1 / Stack templates 포함)  │
│   - ecs@mappings component template                       │
│   - logs-baseline-{namespace} (reindex source)            │
│   - logs-{case}-{namespace} (matrix data streams)         │
└──────────────────────────────────────────────────────────┘
```

### 4.2 매트릭스 정의

```
case = {mode}.{src}.{codec}.{idx}.{dv}.{parsing}
datastream = logs-{case}-{namespace}

mode    ∈ std (standard) / ldb (logsdb) / tsds (time_series)
src     ∈ str (stored)   / syn (synthetic)
codec   ∈ lz4 (default)  / zstd (best_compression)
idx/dv  = if/df (event.original index/doc_values 항상 false)
parsing ∈ p1 (event.original-only) / p2 (event.original + parsed) / p3 (parsed-only)
```

→ **3 × 2 × 2 × 3 = 36 케이스 / dataset**

### 4.3 데이터셋 3 종

| dataset | namespace | 형식 | 평균 메시지 | 10 MB raw 시 docs |
|---|---|---|---|---|
| **firewall** | `default` | Fortinet KV syslog · plain text · 한 줄 = 한 이벤트 | 620 B | ~17,944 |
| **web** | `service` | nginx-like access · request · error 70/25/5 · NDJSON · Elastic Agent 메타 (host/agent/log) 동봉 | 245 B | ~43,370 |
| **snmp** | `snmp` | 12-field pipe-separated positional · plain text · 7 장비 60초 폴링 시뮬레이션 | 55 B | ~191,965 |

### 4.4 baseline 의 역할

`logs-baseline-{namespace}` 는 reindex 의 source. 모든 case 가 이 baseline 에서 reindex 됨. 비교 표에는 분모 (raw_size_bytes) 와 비교되지 않음 (별도 임시 저장소).

### 4.5 raw_size_bytes 의 통일 — message-only 기준

dataset 별 메시지 + 메타 비중이 달라서 ("10 MB 인입" 의 의미가 달라지는 문제), generator 가 **메시지 텍스트만의 누적량** 으로 target 을 측정.

| dataset | 파일에 들어가는 것 | raw_size_bytes 로 기록되는 값 |
|---|---|---|
| firewall | plain text (=메시지) | 파일 크기 = 메시지 합 |
| web | NDJSON (메시지 + 메타) | **메시지 합만** 카운트 (NDJSON 파일은 더 큼) |
| snmp | plain text (메타 없음) | 파일 크기 = 메시지 합 |

→ 같은 "10 MB" target 이 모든 dataset 에서 같은 의미.

---

## 5. 기능 설명

### 5.1 New run 위저드 (4-step)

| Step | 동작 |
|---|---|
| 1. 클러스터 연결 | host/user/password 입력 → `POST /api/cluster/test`. 버전·라이선스 자동 감지, ZSTD/synthetic 지원 배지 |
| 2. 데이터 인입 | dataset 라디오 (firewall/web/snmp) + 목표 용량 (10 MB ~ 1 GB) 선택. seed 는 코드 고정 |
| 3. 비교 조건 | 4 그룹 chip: Index mode / Source mode / Codec / Parsing. 케이스 카운트 + 64 케이스 초과 경고 |
| 4. 실행 + 진행률 | SSE + 2 초 status 폴링 fallback. generate% / ingest% / 케이스별 reindex% / force_merge / 완료 칩 |

### 5.2 Reports / RunDetail

**Reports**: 누적 run 목록 (시각·라벨·dataset·상태·클러스터·case 수·raw size). 3 초 자동 새로고침. 행별 휴지통.

**RunDetail**:
- 저장 크기 막대 차트 (Y 축 절대 크기, 원본 굵은 점선 오버레이)
- 케이스 표 (가운데 정렬, ±% 표기, 풀어쓴 라벨)
- **"어떤 설정이 저장 공간을 가장 크게 바꾸는가"** — 축별 영향 순위 카드 (격차가 큰 순서로)
- **"다시 측정"** — reindex 없이 measurement 만 재실행 (force_merge 직후 stale 값 보정)

### 5.3 Cleanup

클러스터의 lab-소유 ds 정리 전용. **고정 4 패턴**으로 자동 매치:

```
logs-ldb*-*       # 모든 namespace 의 logsdb 케이스
logs-std*-*       # 모든 namespace 의 standard 케이스
logs-tsds*-*      # 모든 namespace 의 TSDS 케이스
logs-baseline-*   # 모든 namespace 의 baseline
```

체크박스 선택 + 확인 모달. pipeline / index template 은 절대 건드리지 않음 (안전 가드 3겹).

### 5.4 백엔드 핵심 설계

| 결정 | 이유 |
|---|---|
| 클러스터 자격증명을 매 요청에 받음 | 다중 클러스터 비교 가능. 비번은 메모리에만 |
| TLS 검증 강제 끔 | 사내 self-signed 인증서 환경 |
| reindex / force_merge 모두 `wait_for_completion=false` + `_tasks` 폴링 | TB 데이터 인입 시 HTTP 타임아웃 방지 |
| 측정 직전 `_refresh` + 400ms sleep | force_merge 직후 store stats 가 lazy 한 race 완화 |
| SSE 가 cursor 폴링 기반 | `asyncio.Queue` 의 cross-thread wakeup 버그 회피 |
| `composed_of: ["ecs@mappings"]` | ECS 표준 매핑을 자동 상속 |

---

## 6. 핵심 개념 — 어디서 무엇이 압축되는가

### 6.1 ES 저장 구성요소

| 구성요소 | 무엇 | 누가 결정 |
|---|---|---|
| `inverted_index` | term → posting list (검색용) | 매핑 `index=true` |
| `doc_values` | 필드 → 값 (정렬·집계 columnar) | 매핑 `doc_values=true` |
| `stored_fields` | `_source` raw byte stream | `_source.mode=stored` 또는 `store=true` |
| `_ignored_source` | synthetic 이 재구성 못 한 raw 값 폴백 | `_source.mode=synthetic` + 매핑 비활성 |
| `points`, `norms` | numeric range / text scoring | 별도 |

### 6.2 4 축의 진짜 역할

| 축 | 무엇을 한다 | 영향 받는 곳 |
|---|---|---|
| **codec** (LZ4/ZSTD) | byte stream dictionary 압축 | `stored_fields` + `_ignored_source` 만 |
| **source mode** (stored/synthetic) | _source 저장 방식 결정 | stored_fields 양 |
| **매핑 (idx/dv)** | inverted/doc_values 생성 여부 | 그 필드의 inverted_index_b / doc_values_b |
| **index mode** (std/ldb/tsds) | segment 안 정렬 순서 결정 | doc_values 압축 효율 |

### 6.3 ⚠ "logsdb 가 압축" 은 오해

흔한 오해: "logsdb 를 켜면 ES 가 압축을 강하게 한다"

**정확히는:**
- 압축의 일꾼은 **codec(ZSTD)** (stored_fields/_ignored_source 의 byte 압축)
- **logsdb mode 자체** 가 추가로 하는 일은 sort by `@timestamp` (+ 있으면 host.name) → doc_values 가 정렬된 상태로 약간 더 압축
- 우리 실측에서 `std.syn.zstd.p1` (-80.7%) vs `ldb.syn.zstd.p1` (-80.9%) → mode 차이는 **0.2%p**

→ 81% 의 절감은 거의 전부 **`synthetic + 매핑 비활성(if-df) + ZSTD`** 조합이 만드는 것. logsdb 의 mode 비트는 그 위에 얹은 sort 양념 정도.

### 6.4 `_ignored_source` 가 핵심 통로인 이유

우리 case template 의 매핑:
```json
"event.original": { "index": false, "doc_values": false, "ignore_above": 8192 }
```

synthetic 모드에서 ES 가 _source 재구성 시:
1. doc_values 에서 가져오기 → ❌ (doc_values=false)
2. stored field 에서 가져오기 → ❌ (store 안 함)
3. → **`_ignored_source` 메타필드에 raw 값 저장해두고 거기서 읽음**

`_ignored_source` 도 stored_fields 와 같은 codec (LZ4/ZSTD) 으로 byte 압축.

→ 결과: **모든 메시지의 event.original 텍스트가 `_ignored_source` 에 들어가고 ZSTD 로 압축**. firewall p1 의 -81% 는 이 메커니즘.

### 6.5 TSDS 의 진짜 차이 — doc_values 시계열 압축

TSDS 는 _ignored_source 압축은 ldb 와 동일하게 받음. **추가로** doc_values 쪽에서 폭발적 압축:

```
TSDS 의 segment 안 doc 정렬:

[tsid_A: doc(t=0), doc(t=60s), doc(t=120s), ..., (한 시계열 270개)
 tsid_B: doc(t=0), doc(t=60s), doc(t=120s), ...,
 tsid_C: doc(t=0), doc(t=60s), ...]
```

→ 같은 시계열의 시간 시퀀스가 디스크 상 인접. 그 결과:

| 필드 | 알고리즘 | 효과 |
|---|---|---|
| **dimension** (한 tsid 안 상수) | Run-length / constant block | 같은 값 N 번 반복 → "값 × N" 한 줄로 |
| **`@timestamp`** (일정 간격) | Delta-of-delta | 60s 간격이면 첫 delta 60000 후 0,0,0,... → 거의 0 bit |
| **counter metric** (단조 증가) | Delta + bit-pack | 작은 양수 delta 만 저장 |

ldb 는 sort key 가 @timestamp 만이라 다른 시계열들이 섞이므로 위 알고리즘이 작동 안 함.

### 6.6 TSDS 의 제약 — 데이터 유실 메커니즘

TSDS 의 강력한 압축은 **`_id` 자동 생성 규칙** 때문에 가능하지만, 같은 규칙이 데이터 유실의 함정이 됩니다.

#### `_id` 가 자동 결정되는 방식

| 인덱스 종류 | `_id` 결정 |
|---|---|
| 일반 인덱스 | ES 가 랜덤 UUID → 충돌 없음 |
| **TSDS** | **`hash(_tsid, @timestamp)`** ← `_tsid = hash(routing_path 의 dimension 값들)` |

→ **같은 dimension 조합 + 같은 timestamp = 같은 `_id`** → 두 번째부터는 **`version_conflict_engine_exception`** 으로 reject.

이게 시계열 메트릭의 idempotency 를 보장하는 의도된 동작이지만, 데이터 특성이 안 맞으면 대량 유실로 이어집니다.

#### 유실이 발생하는 5 가지 시나리오

| # | 시나리오 | 발생 조건 |
|---|---|---|
| ① | **dimension cardinality 부족** | routing_path 의 unique 조합이 너무 적어 같은 `_id` bucket 에 doc 가 몰림 |
| ② | **dimension 필드 부재** | doc 에 routing_path 필드가 없으면 `_tsid` 가 단일 값으로 collapse |
| ③ | **`@timestamp` 정밀도 부족** | 같은 ms 의 같은 시계열 doc 2 개 이상 → 두 번째 reject |
| ④ | **`look_back_time` / `look_ahead_time` 범위 밖** | 옛 데이터 reindex 시 lookback (default 2h, max 7d) 밖이면 reject |
| ⑤ | **dimension 매핑 불일치** | source 의 dimension 타입이 dest 와 다르면 ignore_malformed 로 missing 처리 |

#### 우리 web dataset 의 실측 — 98% 유실

```
routing_path = host.name + service.name
  host.name 4 unique × service.name 1 unique  →  _tsid 종류 = 4 개뿐

generator 가 0.05초 step → 같은 ms bucket 에 다수 doc 충돌
↓
인입 시도: 12,998 docs   →   살아남음: 302 docs   (98% 유실)
```

→ web 에서 TSDS 비추천. dimension 후보 cardinality 가 너무 낮음.

#### 안전한 TSDS 사용 체크리스트

| 점검 | 권장 |
|---|---|
| dimension 조합 cardinality | 최소 수백 이상, 이상적으로 수천 |
| `@timestamp` 정밀도 | 최소 ms, 폴링 간격 짧으면 µs/ns |
| routing_path 필드가 모든 doc 에 존재 | parsing pipeline 에서 보장 (없으면 reject) |
| `@timestamp` 가 look_back/ahead 안 | 최근 데이터만. 옛 데이터 reindex 시 lookback 미리 늘리기 |
| dataset 본질이 시계열인가 | 이벤트 로그면 logsdb / standard 가 더 안전 |

#### 우리 매트릭스 기준 안전도

| dataset | dimension 그룹 수 | 안전? |
|---|---|---|
| **snmp** | 7 device × 24 if × 4 metric ≈ 700 | ✅ 60초 간격, 충돌 없음 |
| **firewall** | source.ip × destination.ip ≈ 수만 (random IP) | ✅ cardinality 매우 높음 |
| **web** | host.name 4 × service.name 1 = 4 | ❌ 98% 데이터 유실 |

#### ES 가 알려주는 신호 (현재 미노출, 개선 후보)

reindex 후 `_tasks/{id}` 응답에 `failures: [...]` 의 version_conflict 메시지가 들어옴. 우리 도구의 `reindex_done` 이벤트에 `n_failures` 가 들어있지만 UI 에 자동 배지로는 안 띄움. 향후 "이 케이스는 N% 데이터 유실됨" 경고 추가 후보.

### 6.7 비유로 한 줄

```
검침 일지 비유:
  ldb (시간순):   01월 김의가스=12345, 이의가스=8900, 박의가스=20100,
                  02월 김의가스=12580, 이의가스=8902, 박의가스=20103,
                  → 매번 큰 숫자 무작위, 압축 거의 안 됨

  TSDS (사람순): 김의가스 [12345, +235, +230, +235, ...]
                 이의가스 [8900,  +2,   +5,   +1,   ...]
                 박의가스 [20100, +3,   +4,   +2,   ...]
                 → 차이만 작은 수, 비트-팩으로 매우 작게 저장
```

---

## 7. 실측 결과

### 7.1 데이터셋별 1 위 케이스

| dataset | 1 위 | store / raw | vs raw | 1 위가 다른 이유 |
|---|---|---|---|---|
| **firewall** (긴 KV 로그) | `ldb.syn.zstd.p1` | 1.91 MB / 10 MB | **-80.9%** | 메시지 한 줄이 길어 ZSTD 의 dictionary 압축이 강력. `_ignored_source` 하나에 모든 절감 집중 |
| **web** (메시지 + 메타) | `ldb.syn.zstd.p3` | 230 KB / 3 MB | **-92.7%** | 메타가 doc_values 로 재구성, parsed 필드도 작아서 인덱스 비용 최소 |
| **snmp** (메트릭 시계열) | `tsds.syn.zstd.p3` | 3.35 MB / 10 MB | **-66.5%** | TSDS doc_values 압축의 시계열 효과. ldb (-44.3%) 보다 22%p 우세 |

### 7.2 mode 의 효과 (같은 codec/source/parsing 비교)

**firewall** (p3, syn, zstd):
| | store | vs raw |
|---|---|---|
| std | 2.99 MB | -70.1% |
| ldb | 2.95 MB | -70.5% |
| tsds | 2.60 MB | -74.0% |

→ TSDS 가 미세하게 우세 (~4%p). 이벤트 로그 (high-cardinality IP) 라 시계열 효과 작음.

**snmp** (p3, syn, zstd):
| | store | vs raw |
|---|---|---|
| std | 5.83 MB | -41.7% |
| ldb | 5.57 MB | -44.3% |
| **tsds** | **3.35 MB** | **-66.5%** |

→ **TSDS 가 압도 (+22%p vs ldb)**. 시계열 메트릭이라 dimension grouping + delta encoding 폭발.

**web** (p3, syn, zstd):
| | store | vs raw |
|---|---|---|
| std | 1.05 MB | -66.0% |
| ldb | 882 KB | -72.0% |

### 7.3 codec 의 효과 (LZ4 → ZSTD 절감)

| dataset | 절감 폭 | 이유 |
|---|---|---|
| **firewall** | -10 ~ -30 %p (p2 stored 에서 가장 큼) | KV 키 (`date=`, `srcip=` ...) 가 doc 안에서 반복 → dictionary 효과 |
| **web** | -10 ~ -25 %p | 메타 (host.name, agent.name 등) 가 모든 doc 에서 동일 → 압축 잘 됨 |
| **snmp** | -5 ~ -15 %p | 메시지가 짧고 (55 B) doc 안 반복 substring 적음 → 효과 제한적 |

→ **codec 의 가치는 byte stream 안의 반복 substring 양에 비례**. 메시지가 길고 반복 패턴이 많을수록 효과 큼.

### 7.4 parsing 의 효과 (p2 → p3)

거의 모든 dataset 에서 p3 가 가장 작음. p2 는 raw + parsed 가 동시에 _source 에 들어가 사실상 정보 중복 → 가장 비쌈.

| dataset | p2 평균 (ldb·syn·zstd) | p3 평균 (ldb·syn·zstd) | 절감 |
|---|---|---|---|
| firewall | -53.8% | -70.5% | -16.7%p |
| web | -56.0% | -72.0% | -16.0%p |
| snmp | -25.7% | -44.3% | -18.6%p |

→ **검색에 raw 텍스트가 필요 없으면 p3 가 단연 1순위**.

### 7.5 source mode 의 효과 (stored → synthetic)

| dataset | 절감 폭 | 이유 |
|---|---|---|
| **firewall** | -25 ~ -35 %p | parsed 필드가 doc_values 로 재구성 → stored_fields 0 |
| **web** | -15 ~ -30 %p | 동일 |
| **snmp** | -5 ~ -15 %p | event.original 매핑이 비활성이라 어차피 `_ignored_source` 폴백, 메시지가 짧아 절감 폭 제한적 |

→ synthetic 의 가치는 **매핑이 정상이고 stored_fields 가 큰 비중일 때** 극대화. 매핑 비활성 + 짧은 메시지면 효과 작음.

---

## 8. 운영 권장 매트릭스

### 8.1 시나리오별 추천

| 시나리오 | 추천 조합 | 예상 절감 |
|---|---|---|
| 콜드 보관 (검색 불필요, 텍스트 보존) | `ldb.syn.zstd.p1` | -70 ~ -85% |
| HOT — ECS 필드 검색 + raw 보존 | `ldb.syn.zstd.p2` | -25 ~ -55% |
| WARM — ECS 필드 검색만 (raw 버림) | `ldb.syn.zstd.p3` | -40 ~ -90% |
| **시계열 메트릭** | `tsds.syn.zstd.p3` | -65 ~ -85% (snmp 데이터) |
| ❌ 피해야 할 조합 | `std.str.lz4.p2` | +2 ~ +30% (원본보다 큼) |

### 8.2 mode 선택 가이드

```
데이터가 무엇인가?
├─ 이벤트 로그 (firewall, audit, application log)
│   → ldb 또는 std (사실상 무차)
│   → 진짜 절감은 codec(ZSTD) + synthetic 에서
│
├─ 저-cardinality 메타가 많은 로그 (web access 등)
│   → ldb 가 1위 (host.name 같은 메타가 columnar 압축에 잘 맞음)
│
└─ 시계열 메트릭 (SNMP, app metrics, IoT 센서)
    → TSDS 강력 권장
    → dimension cardinality 가 100 이상은 되어야 효과적
    → 너무 적으면 _id 중복 거부 위험 (web 사례)
```

### 8.3 parsing 선택 가이드

```
검색 요구사항?
├─ raw 텍스트 검색 (grep-style) 필요
│   → p1 또는 p2 + event.original 매핑 활성화 (이번 매트릭스 밖)
│
├─ ECS 필드 검색만 (source.ip, event.action 등) 필요
│   → p3 (가장 작고 가장 빠름)
│
└─ 두 가지 모두 + 원본 보존
    → p2 (가장 비쌈, 마지막 옵션)
```

---

## 9. 만드는 과정 — 마일스톤 흐름

| 마일스톤 | 핵심 변경 |
|---|---|
| **M1** | FastAPI + React/TS 골격, 4-step 위저드, SSE 진행률, SQLite. Basic 12 케이스 |
| **M1.5** | SSE 폴링 재설계, force_merge 비동기화, 측정 안정화 (refresh+sleep), run 삭제, "다시 측정", Cleanup 페이지 |
| **M2** | 매트릭스 재정의 (`composed_of: ecs@mappings`, idx/dv scenarios → 40 케이스) |
| **M2.1** | event.original idx/dv 를 if/df 로 고정. 24 케이스로 축소 |
| **M3** | web dataset 추가 (NDJSON, Agent 메타). raw_size_bytes 를 message-only 기준 통일 |
| **M3.5** | snmp dataset 추가 (12-field positional, 메타 없음) + cleanup 패턴 단순화 (`logs-*-*` 와일드카드) |
| **M4** | **TSDS mode 추가**. 36 케이스 / dataset. dataset 별 routing_path + dimension/metric 매핑 |

### 진행 중 발견한 큰 함정 3 가지

| 함정 | 원인 | 해결 |
|---|---|---|
| TSDS template PUT 실패 (silent fallback to logsdb) | `look_ahead_time: 30d` 가 ES max(7d) 초과 | `7d` 로 수정 |
| web 의 TSDS doc 99% 거부 | dimension cardinality 4 → 같은 (_tsid, ts) 의 _id 중복 | 디자인 한계로 인정. web 에서 TSDS 비추천 |
| measurement race | force_merge 직후 store stats lazy | `_refresh + 400ms sleep` + RunDetail "다시 측정" 기능 |

---

## 10. 부록 — 자주 묻는 오해 정리

### Q1. "logsdb 를 쓰면 압축이 잘 된다" 가 맞는 말인가?

→ **반은 맞고 반은 틀림**. logsdb mode 자체의 압축 기여는 sort 효과로 0.2%p 수준. 같이 켜지는 synthetic + codec(ZSTD) 가 진짜 일꾼.

### Q2. `index.codec` 이 모든 인덱스 데이터를 압축하나?

→ ❌. **`stored_fields` 와 `_ignored_source` 에만** 작동. inverted_index 와 doc_values 는 Lucene 자체 압축 (codec 무관).

### Q3. synthetic _source 가 항상 이득인가?

→ ❌. 매핑이 정상이면 큰 이득이지만, 매핑이 비활성 (index=false, doc_values=false) 인 큰 텍스트 필드가 _source 대부분이면 그 필드는 `_ignored_source` 로 폴백되어 stored 와 거의 같아짐.

### Q4. TSDS 가 모든 시계열에 적합한가?

→ ❌. **dimension cardinality 가 충분히 높아야** 함. 너무 적으면 (web 사례) 같은 (_tsid, timestamp) 의 doc 이 중복 거부되어 **데이터 대량 유실** (실측 12,998 → 302, 98%). 적당해야 (SNMP 사례) doc_values 압축이 폭발.

자세한 메커니즘과 안전 체크리스트는 **§6.6 TSDS 의 제약 — 데이터 유실 메커니즘** 참조.

### Q5. ignore_above 가 우리 매트릭스에서 의미 있나?

→ ❌. event.original 매핑이 처음부터 index=false, doc_values=false 이라 ignore_above 가 트리거되어도 추가로 막을 게 없음. 모든 doc 이 어차피 `_ignored_source` 로 폴백. ignore_above 가 의미 있으려면 매핑 한쪽이라도 활성이어야 함 (별도 검증 매트릭스가 필요).

---

## 11. 향후 과제

- 옵션 ② **서버 경로 인입** (현재는 합성 로그만)
- run 간 **diff 비교** (같은 dataset 다른 시점)
- 결과 **CSV / HTML 다운로드** 버튼
- **동시 다중 run** (현재 단일 worker 직렬)
- 케이스 간 **병렬 reindex** (concurrency 토글)
- ignore_above / wildcard / dynamic mapping 등 **매핑 토글 매트릭스** 부활 (96 case 시절의 옛 매트릭스)
- TSDS 의 **lookback 큰 데이터 (TB 단위)** 검증

---

## 12. 도구 / 파일 위치

```
R&D/
├── UI_요구사항.md                  요구사항 정의
├── notion_*.md                    노션 정리용 문서들
├── data/, results/, scripts/      기존 CLI (보존, webapp 이 사용 안 함)
├── pipelines/
│   ├── raw_ingest.json            firewall baseline
│   ├── parsing2_full.json
│   ├── parsing3_parsed_only.json
│   ├── raw_ingest_service.json    web baseline
│   ├── parsing2_full_service.json
│   ├── parsing3_parsed_only_service.json
│   ├── raw_ingest_snmp.json       snmp baseline
│   ├── parsing2_full_snmp.json
│   └── parsing3_parsed_only_snmp.json
└── webapp/
    ├── backend/   FastAPI + .venv
    └── frontend/  Vite + React + TS
```

실행:
```powershell
# 백엔드
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8766 --reload --reload-dir app

# 프론트 (별도 터미널)
$env:Path += ";C:\Program Files\nodejs"
npm run dev
# → http://localhost:5173
```

---

## 13. 결론

이 R&D 도구로 확인된 본질은 단순합니다:

```
저장 효율 = ∑(필드 × 그 필드의 매핑이 만든 구성요소)

  ↓ 이걸 줄이는 방법은
  
1) 필드 자체를 줄인다             →  parsing p3 (event.original 제거)
2) 매핑을 비활성한다              →  if-df (inverted/doc_values 안 만듦)
3) _source 를 매핑 기반 재구성    →  synthetic
4) 남은 byte stream 을 압축       →  codec(ZSTD)
5) doc_values 를 잘 정렬하면 더 압축→  TSDS (시계열) 또는 logsdb (시간순)
```

→ 어떤 데이터셋이든 이 5 단계를 각각 적용하면 압축이 누적. 다만 단계마다 효과가 데이터 특성에 의존:
- 메시지가 길면 4 가 결정적
- doc 수가 많고 시계열이면 5(TSDS) 가 결정적
- raw 검색이 필요 없으면 1(p3) 이 압도

실측이 보여준 가장 큰 결론은 **"mode 보다 codec, codec 보다 parsing 이 더 큰 단일 변수"** 라는 것. 운영 우선순위를 그 순서로 잡으면 됩니다.
