# Elasticsearch 저장 효율 — 4 축의 역할과 실측 인사이트

R&D 환경(ES 9.3.1, 4 노드)에서 firewall / web / java 3 데이터셋 × 24 케이스 매트릭스로 측정한 결과를 기반으로 정리.

---

## 1. Index mode — `standard` vs `logsdb`

### 역할

ES 8.x+ 부터 추가된 **시계열 로그 전용 인덱스 모드**.

| 측면 | standard | logsdb |
|---|---|---|
| `@timestamp` 기준 정렬 | × | ✅ 자동 강제 |
| `_source` 기본 모드 | stored | synthetic 권장 |
| doc_values 압축 | 표준 (delta+bit-pack) | **정렬된 데이터 추가 압축** (delta-of-delta 등 더 강력) |
| inverted index 압축 | 표준 | sort 순서 기반 약간 더 압축 |

→ 핵심: **doc_values 가 sort 된 상태에서 더 잘 압축됨**.

### 실측 결과

| 데이터셋 | std → ldb 평균 절감 | 비고 |
|---|---|---|
| firewall (Fortinet KV) | **~0.5 %p** | source.ip / port 가 랜덤이라 sort 이점 거의 없음 |
| web (nginx + 메타) | **-3 ~ -9 %p** | host.name, agent.name 같은 낮은 cardinality 메타가 columnar 압축에 매우 유리 |
| java (stack trace) | **~0.5 %p** | 메시지 byte 가 압도적 비중이라 doc_values 효과 묻힘 |
| 96-case (옛 wildcard 매핑) | **~56 %p (ldb 56% / std 113%)** | event.original 의 wildcard n-gram doc_values 가 거대 → ldb 정렬 압축이 폭발 |

### 결론

- logsdb 의 이득은 **doc_values 가 클 때만** 발휘됨
- 메타 필드 cardinality 가 낮고 sort 가능하면 효과 큼
- 큰 raw 텍스트 / 무작위 값 위주면 효과 거의 없음

---

## 2. Source mode — `stored` vs `synthetic`

### 역할

`_source`(원본 JSON 도큐먼트) 를 disk 에 저장하는 방식.

| 측면 | stored | synthetic |
|---|---|---|
| `_source` 저장 | byte stream 으로 그대로 | **저장 안 함** — 검색 시 매핑된 필드에서 재구성 |
| 재구성 소스 우선순위 | — | ① doc_values → ② stored field → ③ `_ignored_source` 폴백 |
| 라이선스 | 전 라이선스 | **Enterprise** (Basic 은 stored 로 fallback) |
| 검색 응답 비용 | 가벼움 (그대로 읽음) | 약간 무거움 (재구성) |

### 실측 결과

| 데이터셋 | stored → synthetic 절감 | 비고 |
|---|---|---|
| firewall | **-30 ~ -70 %p** | p2 에서 가장 큼 (raw + parsed 가 _source 양분) |
| web | **-15 ~ -30 %p** | 메타가 doc_values 로 재구성 → stored_fields 0 |
| **java** | **-1 ~ -4 %p (거의 무차)** | event.original 매핑이 `index=false, doc_values=false` 라 synthetic 이 재구성할 수단 0 → 모든 doc 이 `_ignored_source` 로 폴백 |

### 결론

- 매핑이 정상이면 synthetic 이 **가장 강력한 단일 절감 수단**
- 매핑이 비활성된 큰 텍스트 필드가 _source 대부분이면 synthetic 의 이점 사라짐
- → 비활성 필드라도 ignore_above 가 적당히 작으면 synthetic 효과는 작은 메시지에서만 나옴

---

## 3. Codec — `default (LZ4)` vs `best_compression (ZSTD)`

### 역할

`index.codec` 설정 — Lucene 의 **StoredFieldsFormat** codec 만 선택. **`stored_fields` (= `_source` + `_ignored_source`) 에만 영향**.

| 항목 | LZ4 (default) | ZSTD (best_compression) |
|---|---|---|
| 대상 | stored_fields only | stored_fields only |
| 압축율 | ~3-4× | ~5-8× |
| indexing CPU | 빠름 | 약간 더 씀 |
| ES 버전 | 모든 버전 | **8.19+ 부터 ZSTD** (이전엔 DEFLATE) |
| inverted_index, doc_values | 영향 **없음** | 영향 **없음** |

⚠ **혼동 주의**: ZSTD 가 좋다고 해서 모든 인덱스 압축에 적용되는 게 아님. _source 의 byte stream 압축에만 작동.

### 실측 결과 (LZ4 → ZSTD 절감)

| 데이터셋 | 절감 폭 | 이유 |
|---|---|---|
| firewall | **-10 ~ -30 %p** | 메시지 안 반복 substring 적당 |
| web | **-10 ~ -25 %p** | 메시지 짧지만 메타 반복으로 압축 가능 |
| **java** | **-40 ~ -46 %p** | stack trace 의 `\tat com.wnytech.`, `(file.java:N)` 같은 substring 이 doc 안에서 폭발적으로 반복 → ZSTD dictionary 효과 극대화 |

### 결론

- **byte-level dictionary 압축이므로 반복 substring 이 많을수록 강력**
- 큰 텍스트 + 반복 패턴 (Java, stack trace, JSON 키 반복) → ZSTD 가 압도적
- synthetic + p3 처럼 _source 가 거의 0 인 케이스에서는 ZSTD 효과도 작음 (압축할 대상이 없음)

---

## 4. Parsing — `p1` / `p2` / `p3`

### 역할

ingest pipeline 으로 raw 메시지를 처리하는 방식.

| 토큰 | 의미 | 결과 doc 의 _source |
|---|---|---|
| **p1** | event.original-only | raw 메시지만 |
| **p2** | event.original + parsed | raw + 파싱된 ECS 필드들 (둘 다) |
| **p3** | parsed-only | 파싱된 ECS 필드만 (raw 제거) |

### 실측 결과

크기 순서는 거의 모든 dataset 에서 **p3 < p1 < p2** (p3 가 가장 작고 p2 가 최악):

| Case 비교 (ldb.syn.zstd 기준) | firewall | web | java |
|---|---|---|---|
| p3 (parsed-only) | -70.7% | **-73.6%** | **-96.7%** |
| p1 (event.original-only) | **-81.1%** | -72.7% | -85.1% |
| p2 (event.original + parsed) | -54.0% | -56.0% | -82.8% |

**예외**: java p1 이 p3 보다 더 작음. event.original 매핑이 비활성이라 `_ignored_source` 의 byte 만 ZSTD 압축되는데, p1 은 단일 필드 1개라 압축율이 매우 높음. p3 는 parsed 필드들의 doc_values 비용이 더 큼.

### 결론

- **raw 텍스트가 검색·집계에 필요 없으면 p3 가 압도적**
- p2 는 raw 와 parsed 를 둘 다 저장 → 사실상 정보 중복. 가장 큰 비용
- raw 검색이 필요하면 p1 사용 + event.original 매핑 활성화 (이번 매트릭스 밖)

---

## 5. 종합 — 어떤 축이 얼마나 영향을 주는가

각 축을 정반대로 바꿨을 때의 평균 절감 폭 (실측 기반):

| 축 변경 | firewall | web | java |
|---|---|---|---|
| std → **ldb** | ~0.5 %p | -3 ~ -9 %p | ~0.5 %p |
| stored → **synthetic** | **-30 ~ -70 %p** | -15 ~ -30 %p | -1 ~ -4 %p |
| LZ4 → **ZSTD** | -10 ~ -30 %p | -10 ~ -25 %p | **-40 ~ -46 %p** |
| p2 → **p3** | **-50 ~ -80 %p** | -50 ~ -65 %p | -75 ~ -80 %p |

### 핵심 인사이트 한 줄씩

1. **parsing 선택 (p2 ↔ p3) 이 가장 큰 단일 변수** — 정보 중복을 없애는 가장 직접적 수단
2. **synthetic 의 가치는 매핑에 의존** — 매핑이 정상이면 압도적, 비활성 필드면 효과 없음
3. **ZSTD 는 데이터셋 특성에 강한 의존** — 반복 substring 이 많은 데이터에서 효과 폭발
4. **logsdb 의 이득은 doc_values 가 큰 곳에서만** — wildcard, 낮은 cardinality 메타 등에서

### 운영 권장 조합

| 시나리오 | 추천 조합 | 예상 절감 |
|---|---|---|
| **콜드 보관 (검색 불필요)** | `ldb.syn.zstd.if.df.p1` | -81 ~ -97% |
| **HOT (ECS 필드 검색 + raw 보존)** | `ldb.syn.zstd.if.df.p2` | -54 ~ -83% |
| **WARM (ECS 필드 검색만)** | `ldb.syn.zstd.if.df.p3` | -71 ~ -97% |
| ❌ 피해야 할 조합 | `std.str.lz4.if.df.p2` | +2 ~ +52% (원본보다 큼) |

---

## 6. 어디서 무엇이 저장되는가 (참고용 매핑표)

| 구성요소 | 무엇 | 영향받는 축 |
|---|---|---|
| `inverted_index` | term → posting list (검색용) | 매핑의 `index=true` |
| `doc_values` | 필드 → 값 (정렬·집계 columnar) | 매핑의 `doc_values=true` + **logsdb** |
| `stored_fields` | `_source` raw byte stream | **stored mode** + **codec (LZ4/ZSTD)** |
| `_ignored_source` | synthetic 이 재구성 못 한 raw 값 폴백 | **synthetic mode** + **codec (LZ4/ZSTD)** |
| `points` / `norms` | numeric range / text scoring | 별도 (codec 무관) |

→ **codec (LZ4/ZSTD) 는 stored_fields + _ignored_source 만 영향**. inverted/doc_values 는 Lucene 자체 압축 사용.

---

작성일: 2026-05-14 / 측정 데이터: firewall · web · java 3 dataset 각 24 케이스 × 10 MB raw
