# Elasticsearch 저장 효율 매트릭스 — 종합 리포트

작성일: 2026-05-13
환경: ES 9.3.1, 4 노드 클러스터 (192.168.200.71)
샘플: Fortinet traffic syslog, 17,944 docs, raw 10,486,256 bytes (10.0 MB)
산출물 위치: `R&D/scripts/`, `R&D/results/`

---

## 0. 한 페이지 요약

- **목적**: Fortinet traffic 같은 대용량 보안 로그를 ES 에 색인할 때, 어떤 옵션 조합이 디스크를 얼마나 쓰는지 실측해서 운영 권장 조합을 도출
- **변수 6 차원**: parsing × index_mode × _source.mode × codec × mapping.index × mapping.doc_values = 96 케이스
- **2 라운드 실측**: (1) `event.original = wildcard`, (2) `event.original = keyword`
- **가장 큰 발견 4 개**:
  1. **`event.original` 매핑이 단일 최대 비용 변수** — wildcard ↔ keyword 한 번 바꾸면 베이스라인이 146% → 82% (-44%p)
  2. **logsdb 의 효과는 wildcard 비용에 의존** — wildcard 면 std 대비 66% 절감, keyword 면 0.2% 절감
  3. **synthetic + idx:F + dv:F 는 함정** — 절약된 doc_values 보다 `_ignored_source` 가 더 큼 (순 손해)
  4. **mapping idx/dv 토글의 효과는 parsing 별로 비대칭** — p1 에서 spread 0%, p3 에서 247%
- **운영 권장**:
  - 풀텍스트 grep 필요: `wildcard + ldb + syn + zstd` (12% 비싸지만 substring 검색)
  - 일반 분석: `keyword + std/ldb + syn + zstd` (logsdb 의미 작음)
  - 검색 불필요: `keyword(idx:F, dv:F)` 또는 ES 밖 객체 스토리지
- **베스트 (p3, 검색만)**: `ldb.syn.zstd.if.dt.p3` = **17.8% of raw**
- **베스트 (p2, 검색+원문)**: `ldb.syn.zstd.if.dt.p2` = **67.8% of raw**
- **워스트**: `std.str.lz4.it.dt.p2` = **151.9% of raw** (원본의 1.5배)

---

## 1. 실험의 의의

### 1.1 배경

Fortinet, syslog, IPS, UTM 같은 보안 로그는 운영 클러스터에서 디스크 비용의 주범. 같은 raw 텍스트도 ES 에 어떻게 색인하느냐에 따라 디스크 사용량이 **수십 배** 차이 남. 그런데 옵션이 너무 많아서 *어느 옵션이 어디에 어떻게 작용하는지* 실측 근거 없이 결정하기 어려움.

### 1.2 목적

각 옵션 조합 (parsing 정책, 인덱스 모드, _source 저장 방식, 압축 코덱, 매핑 토글) 이 저장 사이즈에 미치는 영향을 **개별적·교차적으로 측정**해서:

1. 어떤 차원이 디스크 비용을 결정하는지 (영향력 순위)
2. 차원 간 상호작용 (예: logsdb 가 모든 매핑에 똑같이 효과 있는지)
3. 운영 시나리오별 (검색 / 집계 / 원문 보존) 최적 조합
4. 매트릭스 차원 중 **측정 가치 없는 차원** 식별 (다음 R&D 의 노이즈 제거)

### 1.3 산출물

| 산출물 | 용도 |
|---|---|
| `scripts/` (orchestrator + matrix builder) | 96 케이스 자동 생성·실측 파이프라인 |
| `results/measurements.csv` | 케이스별 원천 측정값 |
| `results/disk_usage_raw.json` | `_disk_usage` 원본 응답 (필드별 분해) |
| `results/report.html` | Plotly 차트 + 정렬 테이블 |
| `results/analysis.md` | 최신 라운드 분석 |
| 본 문서 | 종합 리포트 (실험 의의 ~ 결과 해석) |

---

## 2. 실험 설계

### 2.1 매트릭스 변수 (6 차원)

| 차원 | 값 | 약어 | 의미 |
|---|---|---|---|
| parsing | 1 | p1 | `event.original` 만 (raw 보존, 전처리 없음) |
| | 2 | p2 | 파싱 필드 + `event.original` (풀스펙) |
| | 3 | p3 | 파싱 필드만 (`event.original` 제거) |
| index mode | standard | std | 클래식 디폴트 |
| | logsdb | ldb | 로그 워크로드 최적화 (sorted by @timestamp, columnar dv) |
| `_source.mode` | stored | str | 클래식 raw `_source` 저장 |
| | synthetic | syn | doc_values + inverted_index 에서 `_source` 재구성 (Enterprise) |
| codec | default | lz4 | LZ4 (빠름) |
| | best_compression | zstd | ZSTD (작음, 9.x 부터 DEFLATE → ZSTD) |
| mapping.index | true | it | 인버티드 인덱스 생성 |
| | false | if | 인버티드 인덱스 X (검색 불가) |
| mapping.doc_values | true | dt | doc_values 컬럼 저장 |
| | false | df | doc_values X (집계·정렬 불가) |

조합: 3 × 2 × 2 × 2 × 2 × 2 = **96 케이스** + 베이스라인 1 = 97.

데이터스트림 네이밍: `logs-{mode}.{src}.{codec}.{idx}.{dv}.{parsing}-default`
예: `logs-ldb.syn.zstd.if.dt.p3-default`

### 2.2 데이터셋

Fortinet traffic syslog 합성 데이터:
- 17,944 docs
- raw 텍스트 10,486,256 bytes (10.0 MB)
- 라인당 평균 ~580 bytes
- 시드 고정 (`random.seed(42)`) — 재현 가능
- 다양성: 10 services, 5 interfaces, 4 actions, 다양한 IP/port/byte 분포

라인 예시:
```
2026-03-18 21:15:00 Mar 18 21:15:00 10.10.200.103 date=2026-03-18 time=21:15:00 devname=WNYT-FW-A devid=FG180FTK23902182 eventtime=1773836100000173056 tz=+0900 logid=0000000013 type=traffic subtype=forward level=notice vd=root srcip=78.185.62.255 srcport=6637 srcintf=wan1 ...
```

### 2.3 파이프라인

| 파이프라인 | 역할 | 사용처 |
|---|---|---|
| `raw_ingest` | 원본 텍스트 → `event.original`, `@timestamp` 세팅 | baseline 적재 시 |
| `parsing2_full` | dissect (헤더 6 토큰 제거) → KV → ECS 매핑 | p2 target 의 default_pipeline |
| `parsing3_parsed_only` | parsing2_full 호출 후 `event.original` 제거 | p3 target 의 default_pipeline |
| (없음) | passthrough | p1 target — 베이스라인 그대로 복사 |

**핵심 트릭**: 베이스라인 데이터스트림 1개에 raw 텍스트 적재 → 96 target 에 reindex 시 target 의 `index.default_pipeline` 이 자동 동작 → parsing 변환이 reindex 시점에 일어남.

### 2.4 인덱스 템플릿

각 96 케이스마다 별도 템플릿:
- `index_patterns: ["logs-<case>-default"]`
- `data_stream: {}`
- `priority: 500`
- settings: `index.mode`, `index.codec`, `index.mapping.source.mode`, `index.default_pipeline`
- mappings:
  - `dynamic_templates`: keyword/long/double/boolean 에 idx/dv 토글
  - `properties`: explicit 매핑 (`@timestamp`, `event.original`, `source.ip`, `event.duration` 등)
  - `event.original` 은 dynamic_template 영향 안 받게 properties 로 pin

### 2.5 측정 방법론

각 인덱스마다 다음 순서로 측정:
1. reindex 직후 `_refresh`
2. `_forcemerge?max_num_segments=1&wait_for_completion=true`
3. 다시 `_refresh`
4. `_cat/indices` (`pri.store.size`)
5. `_disk_usage?run_expensive_tasks=true` — 컴포넌트별 (inverted_index, doc_values, stored_fields, points, norms) + 필드별 분해

공통 설정:
- `number_of_shards: 1`
- `number_of_replicas: 0`
- `refresh_interval: 30s`
- 단일 segment 강제 (force_merge) → 측정 노이즈 최소화

---

## 3. 실험 진행 — 두 라운드

### 3.1 1차 라운드 (`event.original = wildcard`)

ECS 표준 권장에 따라 `event.original` 을 `wildcard` 타입으로 설정. 96 케이스 reindex + 측정 완료.

**문제 발견** (사용자 catch): `event.original` 에 KV processor 가 fail 했음. 원인 — 라인 앞쪽 syslog 헤더 (`2026-03-18 00:29:53 Mar 18 18 00:29:53 10.10.200.103`) 가 `=` 없는 토큰들이라 KV processor 가 첫 토큰부터 실패. `ignore_failure: true` 라 silent skip → `_kv` 가 비어 모든 후속 set/copy_from 이 무동작 → **p2/p3 doc 에 파싱 필드 0개**.

**수정**: 파이프라인 맨 앞에 `dissect` 추가 — `"%{} %{} %{} %{} %{} %{} %{_kvstr}"` 로 헤더 6 토큰 제거 후 그 뒤를 KV. 검증: `_simulate` 로 30+ 파싱 필드 정상 생성 확인.

p2/p3 데이터스트림 64개 삭제 → 재 reindex → 재 측정.

### 3.2 2차 라운드 (`event.original = keyword(ignore_above: 8192)`)

1차 결과에서 `event.original` 의 wildcard 비용이 단일 최대 변수임을 발견. 매핑을 keyword 로 바꿔서 동일 96 케이스 재측정. 모든 데이터스트림/템플릿/파이프라인 wipe 후 처음부터 진행.

`ignore_above: 8192` 로 모든 라인 (~700 bytes) 인덱싱 보장.

---

## 4. 실험 결과

### 4.1 차원 평균 ratio (96 케이스 평균)

| 차원 | 1차 (wildcard) | 2차 (keyword) |
|---|---|---|
| parsing p1 | 86.0% | 64.2% |
| parsing p2 | 125.8% | 104.1% |
| parsing p3 | 41.9% | 41.9% |
| mode std | 112.5% | 70.2% |
| mode ldb | 56.6% | 69.9% |
| source str | 97.0% | 82.5% |
| source syn | 72.2% | 57.7% |
| codec lz4 | 92.2% | 77.7% |
| codec zstd | 77.0% | 62.4% |
| idx it | 88.5% | 74.0% |
| idx if | 80.7% | 66.2% |
| dv dt | 82.1% | 67.6% |
| dv df | 87.0% | 72.5% |
| baseline | 145.9% | **82.4%** |

### 4.2 차원별 marginal gain (parsing 별)

| 변환 | p1 (1차→2차) | p2 (1차→2차) | p3 (1차→2차) |
|---|---|---|---|
| std → ldb | 66.0% → **0.2%** | 51.1% → **0.3%** | 0.9% → 1.0% |
| stored → synthetic | 28.9% → 30.3% | 27.3% → 29.3% | 25.1% → 25.0% |
| lz4 → zstd | 7.9% → 8.3% | 17.3% → 18.6% | 25.9% → 25.8% |

**결정적 변화**: logsdb 의 절감폭이 wildcard 일 때만 큼. keyword 로 바꾸면 모든 parsing 에서 무력화.

### 4.3 베스트 / 워스트 (2차 라운드 기준)

| 분류 | 케이스 | pri.store | ratio |
|---|---|---:|---:|
| 최선 (검색만, p3) | `ldb.syn.zstd.if.dt.p3` | 1.87 MB | **17.80%** |
| 최선 (검색+원문, p2) | `ldb.syn.zstd.if.dt.p2` | 7.11 MB | 67.77% |
| 최선 (원문만, p1) | `ldb.syn.zstd.it.dt.p1` | 5.47 MB | 52.21% |
| 워스트 | `std.str.lz4.it.dt.p2` | 15.93 MB | 151.89% |
| 베이스라인 | `logs-baseline-default` | 8.64 MB | 82.4% |

격차: **8.5배** (1차 wildcard 때 12배).

### 4.4 매핑 토글 (idx/dv) 영향 — parsing 별 비대칭

| | spread (1차) | spread (2차) |
|---|---:|---:|
| p1 평균 | 0.0% | 0.0% |
| p2 평균 | (n/a) | 34.0% |
| p3 평균 | (n/a) | 120.0% |
| p3 최대 (`ldb.syn.lz4`) | 247% | 247% |

p1 에서는 토글이 완전히 무의미 — 토글 대상 (keyword/long/bool/double) 필드가 0개. p3 에서는 spread 247% (1.9 MB ~ 6.7 MB).

### 4.5 컴포넌트 분해 (대표 케이스, 2차 라운드)

ldb.syn.zstd 기준:

| 케이스 | inverted | doc_values | stored | _ignored_src | pri |
|---|---:|---:|---:|---:|---:|
| it.dt.p1 | 2,576,098 | 2,806,859 | 43,521 | 0 | 5,474,540 |
| it.dt.p2 | 2,923,505 | 4,047,643 | 43,521 | 0 | 8,280,244 |
| it.dt.p3 | 449,273 | 1,284,090 | 43,521 | 0 | 3,039,320 |
| if.dt.p1 | 2,576,098 | 2,806,859 | 43,521 | 0 | 5,474,540 |
| if.dt.p2 | 2,577,509 | 4,047,643 | 43,521 | 0 | 7,106,732 |
| if.dt.p3 | 103,840 | 1,284,090 | 43,521 | 0 | 1,866,424 |
| if.df.p2 | 2,577,509 | 3,236,952 | 2,145,697 | **2,114,041** | 8,386,151 |
| if.df.p3 | 103,840 | 473,399 | 2,147,855 | **2,116,167** | 3,148,002 |

### 4.6 베이스라인의 변화

| 매핑 | baseline pri | ratio |
|---|---:|---:|
| wildcard | 14.59 MB | 145.9% |
| keyword | 8.64 MB | **82.4%** (-43.5%p) |

베이스라인 = `std.str.lz4.it.dt.p1` 와 동일.

---

## 5. 결과 해석 — 왜 이런 사이즈가 나오는가

### 5.1 왜 p3 < p1 — cardinality 와 정보량

같은 ldb.syn.zstd.it.dt 에서 p1=5.47 MB, p3=3.04 MB. 필드 개수만 보면 p1=1, p3=30 개인데 p3 가 더 작음.

**p1 의 event.original (keyword)**:
- 17,944 docs, 라인 길이 ~580 bytes
- 라인마다 sessionid (10자리 unique), eventtime 나노초 unique, IP/port 다양 → **거의 모든 라인 unique**
- inverted index: 17,944 개 거의 다른 580-byte term → dictionary 자체가 큼 (2.58 MB)
- doc_values: SortedSetDocValues 가 모든 unique string 을 sorted → 2.81 MB

**p3 의 파싱 필드 30개**:
- `service`: 10 unique 값 (HTTPS/HTTP/RDP/...) → 17,944 docs 가 같은 term 10개 공유
- `action`: 4 unique (accept/deny/close/timeout)
- `devname`: 3, `subtype`: 3, `level`: 3
- `srcip`/`dstip`: 수천 unique, 단 `ip` 타입 = 8 bytes 고정 → 매우 효율적
- `sentbyte`/`rcvdbyte`: 숫자 long, delta encoding 잘 됨
- 합쳐도 dictionary 작음, doc_values 도 RLE/delta 로 잘 압축

**핵심 원리**: inverted_index + doc_values 사이즈는 **필드 수에 비례하지 않고 cardinality + value 길이에 비례**.

p3 가 작은 이유는 압축이 잘 되어서가 아니라 **정보를 잃었기 때문** — raw 라인을 못 만들지만 구조화 필드만 보관.

### 5.2 왜 p2 가 가장 큼 — 양쪽 비용 합산

p2 = p1 (event.original 비용) + 파싱 필드 (추가 비용). 둘 다 부담:
- inverted: p2 = 2.92 MB (= p1 의 2.58 + 파싱 필드 inv ~0.34)
- doc_values: p2 = 4.05 MB (= p1 의 2.81 + 파싱 필드 dv ~1.24)
- stored: 동일 (synthetic 모드라 무관)

→ p2 가 raw 의 100% 이상이 되는 게 자연스러움.

### 5.3 왜 logsdb 효과가 wildcard 에 의존

logsdb mode 의 핵심 절감 메커니즘 = **doc_values 의 sorted columnar 인코딩**. 큰 doc_values 일수록 절감폭 큼.

| 매핑 | std doc_values | ldb doc_values | 절감 |
|---|---:|---:|---:|
| wildcard p1 | 10.6 MB | 1.69 MB | **84%** |
| keyword p1 | 2.81 MB | 2.81 MB | 0% |

wildcard 의 n-gram doc_values 는 매우 sortable + 패턴 반복 多 → logsdb 의 columnar 압축에 매우 잘 맞음. keyword 의 일반 doc_values 는 압축 여지 작음 → logsdb 무력.

→ **logsdb 의 가치는 wildcard 같은 비싼 doc_values 필드가 있을 때만**. 일반 keyword/long 위주 인덱스에서는 다른 logsdb 효과 (sorted by @timestamp, host fields auto-mapping) 만 남는데 본 실험에서 그 차이는 측정 X.

### 5.4 왜 synthetic + idx:F + dv:F 가 더 큼 — `_ignored_source` fallback

`ldb.syn.zstd.if.dt.p3` (1.87 MB) 와 `ldb.syn.zstd.if.df.p3` (3.15 MB) 비교.

dv 끄는 게 dt 보다 더 큰 이유:

| 구성요소 | if.dt.p3 | if.df.p3 |
|---|---:|---:|
| doc_values | **1.28 MB** | 0.47 MB ↓ |
| stored_fields | 44 KB | 2.15 MB ↑↑ |
| 그중 `_ignored_source` | 0 | **2.12 MB** |

원리:
- synthetic `_source` 는 `_source` 를 저장하지 않고 doc_values + inverted_index + stored_fields 에서 **재구성**
- `index:false + doc_values:false` 인 필드는 **재구성 소스가 0개**
- ES 가 그 필드를 잃지 않으려고 `_ignored_source` 메타필드에 원본 값을 통째로 보관
- `_ignored_source` 는 per-doc stored field — **columnar 압축 안 됨**

산수: dv 끔으로써 -0.81 MB 절약, ignored_source 로 +2.11 MB 추가 → **순 +1.30 MB 손해**.

→ **synthetic 환경에서 dv 끄기는 거의 항상 손해**. doc_values 의 columnar 압축 효율이 _ignored_source 보다 압도적.

### 5.5 왜 p1 의 매핑 토글이 무의미

p1 doc 에 들어있는 필드:
- `event.original` (explicit keyword 매핑, dynamic_template 우회)
- `@timestamp` (explicit date 매핑)

dynamic_template 의 idx/dv 토글 대상 = keyword/long/double/boolean. **p1 doc 에는 토글 대상 필드가 0 개**. 따라서 토글이 가리키는 곳에 아무것도 없음 → 4 가지 토글 콤보가 bit 단위 동일.

p1 의 (mode × source × codec) 8 콤보 안에서 매핑 토글 4 종이 모두 동일 → **24개 → 8개 축소 가능 확인**.

### 5.6 왜 ZSTD 가 p3 에서 더 효과적

| | lz4 → zstd 절감 |
|---|---:|
| p1 | 8.3% |
| p2 | 18.6% |
| p3 | **25.8%** |

ZSTD 는 dictionary 기반 압축. 작은 segment + 다양성 있는 데이터에서 dictionary 학습 효과 큼. p3 는 segment 가 작아 (~1-3 MB) ZSTD 가 dictionary 를 데이터 패턴에 잘 맞춰 학습.

→ **ZSTD 거의 무조건 켜는 게 이득**. decompress CPU 비용은 무시 가능.

### 5.7 왜 베이스라인이 wildcard 에서 raw 보다 컸나

| 매핑 | inverted | doc_values | stored | total |
|---|---:|---:|---:|---:|
| wildcard | 1.45 MB | 10.60 MB | 3.21 MB | 15.30 MB (146%) |
| keyword | ~3 MB | ~3 MB | ~3 MB | 8.64 MB (82%) |

wildcard 는 n-gram 으로 라인을 쪼개 inverted + dv 두 번 저장 → raw 텍스트보다 큼. keyword 는 라인 전체를 한 번만 인덱싱 → raw 비슷.

---

## 6. 운영 권고

### 6.1 시나리오별 매핑 + Tier

| 시나리오 | event.original | parsing | mode | source | codec | idx/dv | 예상 ratio |
|---|---|---|---|---|---|---|---:|
| 풀텍스트 grep + 분석 (HOT) | wildcard | p2 | ldb | syn | zstd | it/dt | ~48% |
| 풀텍스트 grep + 분석 (HOT, 작게) | wildcard | p2 | ldb | syn | zstd | if/dt | ~48% (검색만 토글) |
| Exact match + 분석 (HOT) | keyword | p2 | std/ldb | syn | zstd | if/dt | ~68% |
| 검색·집계만 (WARM) | (없음) | p3 | ldb/std | syn | zstd | if/dt | ~18% |
| 원문만 보존 (COLD) | — | — | — | — | — | — | (ES 밖 객체 스토리지 권장) |

### 6.2 절대 피해야 할 조합

- `synthetic + idx:F + dv:F` (모든 parsing) — `_ignored_source` 로 fallback, 순 손해
- `std + str + lz4 + p2` — 풀스펙인데 모든 차원이 비효율 (raw 대비 152%)

### 6.3 차원별 결정 가이드

| 결정 | 권장 |
|---|---|
| codec | ZSTD 거의 무조건 (8~26% 절감) |
| _source | synthetic (라이선스 있다면, 25~30% 절감) — 단 dv:F 와 같이 쓰지 말 것 |
| index mode | wildcard 가 있다면 ldb (66% 절감), 아니면 무관 (std/ldb 차이 0.2%) |
| parsing | 시나리오 결정 — p3 최소, p2 풀스펙, p1 raw-only |
| event.original | 풀텍스트 검색 필요 → wildcard, exact 만 → keyword, 검색 X → keyword(F:F) |
| idx/dv 토글 | parsing=p1 이면 무관, p2/p3 면 핵심 변수 |

---

## 7. 매트릭스 차원 축소 결정

본 실험에서 다음 사실 확인:

| 차원 | 매트릭스에 유지 | 이유 |
|---|---|---|
| parsing | 유지 | 가장 큰 단일 변수 |
| index mode | 조건부 유지 | wildcard 있을 때만 의미 |
| _source.mode | 유지 | 모든 조합에서 25~30% 균일 절감 |
| codec | 유지 | 8~26% 절감 |
| mapping idx | **p1 에서 제거 가능, p2/p3 에서 유지** | p1 spread 0%, p2/p3 spread 34~247% |
| mapping dv | 동일 | 단 synthetic + dv:F 조합은 회피 |

p1 의 매핑 토글 24개 → 4개 (또는 8개) 로 축소 가능. **96 → 80 케이스** 가능.

---

## 8. 매트릭스 외 추가 변수 (보조 ablation 실험)

본 매트릭스에 넣으면 폭증하지만 운영에 영향 큰 변수들:

| 변수 | 영향 | 권장 |
|---|---|---|
| `event.original` 매핑 | 단일 최대 비용 | 본 리포트 §5.3 으로 측정됨 |
| `match_only_text` 타입 | wildcard / keyword 의 중간 (full-text 가능, positions X) | 후속 R&D #1 |
| dynamic_template 스코프 (어떤 필드를 토글에 포함) | _ignored_source 양 결정 | 후속 R&D #2 |
| `norms` (text 점수) | norms blob 추가 | 로그 전부 false 고정 권장 |
| `index_options` (docs/freqs/positions/offsets) | inverted index 크기 | 로그는 docs 충분 |
| `multi-field` (text + keyword.raw) | 동일 값 두 번 인덱싱 | ECS 매핑 검토하여 중복 제거 |
| shard 수 / replica | replicas=0 측정 후 곱하기 | 본 실험 1 shard 0 replica 고정 |
| 데이터 cardinality | 압축률 직접 영향 | 후속 R&D #3 (다른 dataset 측정) |

---

## 9. 후속 R&D 우선순위

1. **`event.original` 매핑 5종 비교** — wildcard / match_only_text / keyword(idx:T) / keyword(idx:F, dv:F) / text. 5 케이스 × {p1, p2} × ldb.syn.zstd 만 = 10 케이스로 충분
2. **dynamic_template 스코프 변형** — 어떤 필드 그룹이 _ignored_source 영향 크게 받는지 분리
3. **데이터 cardinality 영향** — 동일 매트릭스를 (a) high-cardinality (b) low-cardinality 두 dataset 으로 비교
4. **logsdb 의 다른 효과 분리** — sorted by @timestamp, host fields auto-mapping 의 기여도
5. **데이터 규모 확장** — 1M docs 이상에서 ratio 안정화 검증

---

## 10. 부록 — 실험 진행상의 교훈

### 10.1 KV processor 의 silent failure (1차 측정 retraction)

- 문제: `event.original` 의 syslog 헤더 토큰이 KV value_split (`=`) 를 가지지 않아 첫 토큰에서 KV 가 fail
- `ignore_failure: true` 로 silent skip → `_kv` 가 비어 후속 set/copy_from 모두 무동작
- 결과: p2/p3 doc 에 파싱 필드 0개. 1차 측정 결과 절반이 가짜
- 검증 누락: `_simulate` 안 돌리고 reindex 진행
- 수정: `dissect "%{} %{} %{} %{} %{} %{} %{_kvstr}"` 로 헤더 6 토큰 제거 후 KV
- 교훈: **ingest pipeline 은 measure 전 simulate 로 출력 검증 필수**

### 10.2 _disk_usage API 응답 포맷 변경 (ES 9.x)

- 이전: `all_fields.doc_values.total_in_bytes` (nested)
- 9.x: `all_fields.doc_values_in_bytes` (flat) — 일부 필드만 nested 유지 (inverted_index)
- 코드 수정: nested 와 flat 둘 다 fallback 처리

### 10.3 dynamic_template 의 explicit field 우회

- `event.original` 을 properties 로 explicit 매핑하면 dynamic_template 의 idx/dv 토글이 우회됨
- p1 에서 토글 효과 0 인 원인이 이것
- 의도적이긴 했음 (event.original 을 매트릭스 차원에서 분리 측정하려고)
- 후속: dynamic_template 스코프에 event.original 을 포함시킨 별도 매트릭스 가치 있음

### 10.4 measurement script 의 견고성

- 96 케이스 자동 측정 → 측정 코드의 작은 버그가 모든 결과 무효화
- 단일 케이스로 dry-run 한 뒤 풀 매트릭스 돌리는 순서 권장
- 본 R&D 에서 `_disk_usage` 포맷 변경 못 잡아서 1차 측정 모두 실패 → 코드 수정 후 재측정
