# ES Storage Lab

Elasticsearch 저장 효율 비교 R&D 도구. 4 축 (Index mode / Source mode / Codec / Parsing) × 3 데이터셋 (firewall · web · snmp) 매트릭스를 UI 위저드로 돌려서 결과를 누적 비교.

> 위앤유텍 사내 R&D 용. 사내 신뢰망에서 사용 가정 (TLS 검증 비활성 기본).

---

## 빠른 시작

### 사전 요구사항

| 항목 | 권장 버전 |
|---|---|
| Python | 3.13+ |
| Node.js | 22 LTS+ |
| Elasticsearch | 8.x+ (`ecs@mappings` component template 포함) |

ES 의 `ecs@mappings` 가 없으면 setup 단계에서 명시적 오류로 멈춥니다. Kibana 첫 부팅 또는 Fleet 셋업 시 자동 등록됨.

### 1) Clone

```bash
git clone https://github.com/WnyTechPrivate/es-storage-lab.git
cd es-storage-lab
```

### 2) 백엔드

```powershell
cd webapp\backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8766 --reload --reload-dir app
```

### 3) 프론트 (별도 터미널)

```powershell
cd webapp\frontend
npm install
$env:Path += ";C:\Program Files\nodejs"   # Windows 에서 PATH 안 잡혀있을 때
npm run dev
```

브라우저: <http://localhost:5173>

> `R&D` 폴더 이름에 `&` 가 들어가는 환경(현 위치)에서는 npm 의 `.bin` shim 이 깨질 수 있어서, `webapp/frontend/package.json` 의 scripts 가 `node node_modules/<tool>/bin/...` 직접 호출로 우회되어 있습니다. `npm run dev` / `npm run build` 그대로 사용 가능.

### 4) 프로덕션 (단일 포트)

```powershell
cd webapp\frontend
npm run build                    # → webapp/frontend/dist/
cd ..\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8766
# → http://<host>:8766  (UI + API 모두 8766 에서 서빙)
```

---

## 한 번에 띄우기 (개발 모드)

| OS | 스크립트 |
|---|---|
| Windows | `scripts\dev-up.ps1` (PowerShell 2 창 띄움) |
| Linux / macOS / WSL | `scripts/dev-up.sh` |

---

## 폴더 구조

```
es-storage-lab/
├── pipelines/                  ES ingest pipelines (dataset 별 3종 × 3)
├── webapp/
│   ├── backend/                FastAPI + uvicorn (8766)
│   │   ├── app/
│   │   │   ├── adapters/       case 명명, ECS template 빌더
│   │   │   ├── services/       generator / setup / ingest / reindex / measure
│   │   │   ├── routes/         cluster / runs
│   │   │   ├── db/             SQLite (runs, measurements)
│   │   │   └── main.py
│   │   └── requirements.txt
│   ├── frontend/               Vite + React + TypeScript (5173 dev)
│   └── README.md               webapp 상세 가이드
├── scripts/                    옛 CLI + dev-up 스크립트
├── UI_요구사항.md               요구사항 정의
└── README.md
```

자세한 webapp 동작 / API / DB 스키마 → [`webapp/README.md`](webapp/README.md)
요구사항·설계 → [`UI_요구사항.md`](UI_요구사항.md)

---

## 핵심 동작 한 줄

1. **Step 1** 클러스터 host/user/password 입력 → 버전·라이선스 자동 점검
2. **Step 2** 데이터셋 선택 (firewall / web / snmp) + 목표 용량
3. **Step 3** 비교 조건 (mode × src × codec × parsing) → **최대 36 케이스 / dataset**
4. **Step 4** 진행률 실시간 표시. 끝나면 Reports 로 자동 이동
5. **Reports / RunDetail** 표 + 차트 + 축별 영향 랭킹. 다시 측정 / 삭제 가능
6. **Cleanup** 클러스터의 lab-소유 ds 정리 (pipeline · template 은 보호)

---

## 데이터셋

| dataset | namespace | 형식 | 평균 메시지 |
|---|---|---|---|
| firewall | `default` | Fortinet KV syslog, plain text | 620 B |
| web | `service` | nginx-like access/request/error 70/25/5 mixed, NDJSON + Elastic Agent 메타 | 245 B |
| snmp | `snmp` | 12-field pipe-separated positional, 7 장비 60초 폴링 | 55 B |

---

## 인사이트 요약 (실측 기반)

| 변경 | firewall | web | snmp |
|---|---|---|---|
| std → ldb | ~0.5%p | -3~-9%p | ~0.5%p |
| stored → synthetic | -25~-35%p | -15~-30%p | -5~-15%p |
| LZ4 → ZSTD | -10~-30%p | -10~-25%p | -5~-15%p |
| p2 → p3 | -16.7%p | -16.0%p | -18.6%p |
| ldb → tsds | ~4%p | (부적합)¹ | **-22%p** |

¹ web 의 TSDS 는 dimension cardinality 4 라서 doc 98% 가 `_id` 중복 거부됨.

자세한 분석 → [노션 종합 리포트 (notion_ES_저장효율_종합리포트.md)](notion_ES_저장효율_종합리포트.md)

---

## License

내부용 (위앤유텍). 별도 라이선스 없음.
