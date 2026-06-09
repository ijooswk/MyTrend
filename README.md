# MyTrend — 뉴스 키워드 트렌드 맵

최근 24시간 뉴스를 여러 소스에서 수집해 키워드를 추출하고, 분야별 트렌드 맵(키워드 네트워크 · 워드클라우드 · 분야별 버블)으로 시각화하는 풀스택 앱.

## 구성

아키텍처: **프론트엔드(nginx)** 와 **백엔드(FastAPI/uvicorn)** 를 별도 이미지로 분리하고, 데이터는 **PostgreSQL** 에 저장한다. nginx가 정적 SPA를 서빙하며 `/api/*`를 백엔드로 프록시한다.

```
MyTrend/
├── backend/                # Python + FastAPI (API 전용)
│   ├── app/
│   │   ├── main.py         # FastAPI 라우트 (API)
│   │   ├── config.py       # 분야·지역·소스·환경설정
│   │   ├── db.py           # PostgreSQL 데이터 계층 (psycopg3 + 커넥션 풀)
│   │   ├── nlp.py          # 키워드 추출(kiwi/휴리스틱) + 트렌드 분석
│   │   ├── ingest.py       # 전 소스 병렬 수집 오케스트레이션
│   │   ├── trends.py       # 캐시 + 미스 시 실시간 보완
│   │   ├── scheduler.py    # APScheduler 주기 수집 + 일일 유지보수
│   │   └── sources/        # 소스 어댑터 (google_news/generic_rss/tavily/eodhd/newsapi)
│   ├── scripts/
│   │   └── migrate_sqlite_to_pg.py  # 옛 SQLite → PostgreSQL 이관(멱등)
│   ├── Dockerfile          # 백엔드 이미지
│   ├── requirements.txt
│   ├── .env.example
│   └── run.sh
├── frontend/
│   ├── index.html          # D3 기반 시각화 UI (상대경로 /api 호출)
│   ├── nginx.conf.template # SPA 서빙 + /api 프록시 (env 치환)
│   └── Dockerfile          # nginx 이미지
├── docker-compose.yml      # 로컬(dev): db + backend + frontend
├── docker-compose.prod.yml # 운영: backend + frontend (DB는 서버 기존 PostgreSQL)
├── manage.sh               # 로컬 Docker 관리
└── deploy.sh               # 원격 서버 배포
```

## 실행

가장 간단한 방법은 Docker다. 로컬 compose는 PostgreSQL까지 함께 띄운다:

```bash
cp .env.example .env     # 선택: 포트/키 설정
./manage.sh up           # db + backend + frontend 빌드·기동
# http://localhost:8000
```

백엔드만 직접 실행하려면 PostgreSQL이 필요하다(`MYTREND_DATABASE_URL`):

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # MYTREND_DATABASE_URL + API 키 입력
uvicorn app.main:app --reload --port 8000
```

## 데이터 소스

| 소스 | 키 필요 | 분야 매핑 | 비고 |
|------|--------|----------|------|
| Google News RSS | ✗ | 경제·사회·과학·테크·세계 × 한국/글로벌 | 기본 활성 |
| 일반 RSS (BBC·연합·한겨레…) | ✗ | 피드별 고정 매핑 | `config.py`에서 자유 추가 |
| Tavily | ✓ `TAVILY_API_KEY` | 분야별 검색 질의 | news 토픽 |
| EODHD | ✓ `EODHD_API_KEY` | 주로 경제/테크 | 금융뉴스 |
| NewsAPI.org | ✓ `NEWSAPI_KEY` | category/country | 선택 |

키가 없는 소스는 자동으로 비활성화되며, 키 없이도 Google News + 일반 RSS만으로 동작한다.

## 피딩 방식 (캐시 + 스케줄)

- **스케줄러**: 시작 시 1회 + `MYTREND_INGEST_INTERVAL_MIN`(기본 360분=6시간)마다 전 소스 수집 → PostgreSQL 적재. 기사 `id`(URL/제목 해시) + `ON CONFLICT` 로 **중복은 자동 흡수**, 새 기사만 추가. 매일 새벽 03시 롤업 + 보존정책 적용.
- **캐시**: 동일 조건 트렌드는 `MYTREND_CACHE_TTL`(기본 120초) 동안 재사용.
- **실시간 보완**: 저장된 데이터가 없는 조건이 요청되면 즉시 수집 후 응답(backfill).

## 키워드 추출

- 한국어: `kiwipiepy` 형태소 분석으로 명사(NNG/NNP) 추출. 미설치 시 조사 제거 휴리스틱으로 폴백.
- 영어: 불용어 제거 + 핵심 약어(AI·GPT·EV 등) 보존.
- 동시출현(co-occurrence)으로 키워드 간 연결(엣지) 계산, 분야 연관도 집계.

## API

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/api/config` | 분야·지역(한/영 라벨)·소스 메타데이터 |
| GET | `/api/trends` | 트렌드 맵 (`categories`,`regions`,`sources`,`hours`,`min_freq`,`max_kw`,`live`) |
| GET | `/api/search` | 키워드 뉴스 검색 (`q`,`regions`,`hours`,`store`). 관련 기사 목록 + 미니 트렌드 반환. `store=true` 면 DB에 병합 |
| GET | `/api/timeline` | 시간버킷별 키워드 빈도 시계열(`keyword`,`buckets` + trends 필터) |
| GET | `/api/correlation` | 상위 키워드 상관 행렬(`metric=npmi|temporal`) — 히트맵용 |
| GET | `/api/history` | 키워드 장기 시계열(롤업 기반, `days`,`interval=day|week|month`) |
| GET | `/api/breakouts` | 과거 베이스라인 대비 급증 키워드(z-score) |
| GET | `/api/seasonality` | 키워드의 주/월/년 반복 주기(자기상관) |
| POST | `/api/rollup` | 저장된 기사를 일별 롤업으로 백필(수동) |
| POST | `/api/ai/relate` | 두 키워드의 상관 관계를 기사 근거로 AI 설명 |
| POST | `/api/ai/radar` | 트렌드 레이더(사분면)의 AI 전략 해설 |
| GET | `/api/export` | 트렌드 키워드를 CSV/JSON 으로 내보내기(`fmt=csv|json` + trends 필터) |
| GET | `/api/ai/status` | AI 사용 가능 여부 + 모델 |
| POST | `/api/ai/briefing` | 현재 트렌드를 자연어 브리핑으로 생성 |
| POST | `/api/ai/label-clusters` | 토픽 군집에 짧은 테마 라벨 부여 |
| POST | `/api/ai/ask` | 현재 기사 제목을 근거로 질문에 답변(RAG-lite) |
| POST | `/api/ingest` | 수동 즉시 수집 |
| GET | `/api/stats` | DB·스케줄러 상태 |
| GET | `/api/health` | 헬스체크 |

## 분석 기능

- **분야**: 경제·사회·과학·테크·세계 + 건강·스포츠·연예(8개, 후자는 기본 비활성/선택형). `config.py`로 손쉽게 확장.
- **키워드 품질**: 한국어 형태소 분석(kiwi) + 인접 명사 복합어 결합, 영어 불용어/약어 처리.
- **연관도(상관) 엔진**: 단순 동시출현 대신 **NPMI**(정규화 점별상호정보, 제목+요약 기준)로 한계빈도를 보정해 *의미있는 상관*만 추출하고, 노드별 백본 필터로 헤어볼을 제거. 임계값으로 밀도 조절.
- **시계열 동조 상관**: 키워드 시계열 피어슨 상관으로 *함께 뜨고 지는* 키워드(동시추세)를 별도 모드로 제공.
- **감성 분석**: 한/영 극성 사전으로 제목 감성 점수(-1~+1) 산출 → 키워드·분야·전체 평균 감성 제공.
- **급상승(모멘텀)**: 시간창을 절반으로 나눠 최근 급증 키워드를 탐지(신규 부상 `NEW` 표시).
- **트렌드 레이더**: 키워드를 모멘텀(추세)×볼륨(빈도) 사분면에 배치 — 주목(Hot)·부상(Emerging)·정착(Established)·쇠퇴(Fading)로 전략 분류. AI가 사분면을 읽어 전략 해설을 제공.
- **토픽 군집**: 동시출현 그래프 라벨 전파(label propagation)로 키워드를 테마 군집으로 묶음.
- **자동 인사이트**: 최다 분야·급상승·허브 키워드·전반 감성·핵심 토픽을 구조화해 제공(프론트에서 다국어 렌더).
- **타임라인**: 키워드별 시간대별 빈도 시계열(스파크라인·드릴다운).
- **내보내기**: 키워드·빈도·분야·감성·연결수·대표기사를 CSV/JSON 으로 추출해 다른 도구/분야에서 재사용.

## 장기 누적 분석 (Production)

수개월~수년 데이터가 쌓이면 의미가 드러나는 분석 레이어. 원시 기사는 일별 **롤업 테이블**(`daily_keyword`)로 집계되어 영구 보존된다. 원시 기사 자체는 `MYTREND_ARTICLE_RETENTION_DAYS` 정책을 따르는데, **기본값 `0`은 무제한(영구 보존)** 이며 양수로 설정하면 그 일수 이후 프루닝된다(롤업은 항상 유지). 매일 새벽 스케줄러가 롤업 후 보존정책을 적용한다.

- **키워드 장기 추이**: 일/주/월 단위 시계열 + GitHub식 **캘린더 히트맵**(History 뷰).
- **돌발 탐지**: 키워드의 *과거 베이스라인 대비* z-score로 비정상 급증을 포착(노이즈가 아닌 진짜 신호).
- **계절성**: 자기상관으로 주/월/년 반복 주기(예: 매년 수능·연말정산) 탐지.
- **롤업 백필**: `POST /api/rollup` 로 기존 기사 전 기간을 한 번에 집계.

> 처음 배포 후 `curl -X POST localhost:8000/api/rollup` 한 번 실행하면 보유 기사가 롤업되며, 이후 매일 자동 누적된다.

## AI 기능 (OpenRouter)

`.env` 의 `OPENROUTER_API_KEY` 가 있으면 활성화된다(없으면 UI가 비활성 표시). 비용/오남용 방지를 위해 **모두 사용자가 버튼으로 호출**하는 온디맨드 방식이며, 동일 입력은 캐시한다(`MYTREND_AI_CACHE_TTL`).

- **트렌드 브리핑**: 현재 트렌드(상위 키워드·급상승·감성·군집)를 LLM이 한/영 자연어 브리핑으로 요약.
- **토픽 자동 라벨링**: 토픽 군집(키워드 묶음)에 짧은 테마 라벨을 부여 → 군집 색상 모드의 범례·툴팁에 표시.
- **트렌드 Q&A**: 질문을 현재 기사 제목들을 근거로 답변(RAG-lite). 근거가 부족하면 그렇다고 답하도록 제약.

프론트엔드 헤더의 **✨ AI** 버튼(단축키 `a`)으로 드로어를 연다. 모델은 `MYTREND_AI_MODEL`(기본 `openai/gpt-4o-mini`)로 변경 가능. LLM 호출은 사용자의 OpenRouter 크레딧을 사용한다.

## 테스트

```bash
cd backend
pip install -r requirements-dev.txt
# DB 비의존 테스트만 실행(아래는 자동 skip)
pytest -q
# DB·API 통합 테스트까지 실행하려면 테스트용 PostgreSQL DSN 지정
MYTREND_TEST_DATABASE_URL=postgresql://mytrend:mytrend@localhost:5432/mytrend_test pytest -q
```

`tests/` 에 키워드 추출(영문 회귀 포함)·복합명사·감성·모멘텀·DB·검색 라우팅·API 스모크 테스트 수록. DB가 필요한 테스트는 `@pytest.mark.pg` 로 표시되며, `MYTREND_TEST_DATABASE_URL` 가 없으면 자동 skip 된다.

## 프론트엔드 기능

- **지역 토글**: 상단에서 한국 / 글로벌 / 통합 전환.
- **다국어**: 한국어 ↔ 영어 UI 전환(선택값은 브라우저에 저장).
- **8종 뷰 + 급상승**: 키워드 네트워크, 워드클라우드, 분야별 버블, 트리맵, 상관 히트맵, 트렌드 레이더, **히스토리(장기 추이·캘린더)**, 급상승 키워드.
- **테마**: 다크/라이트 완전 적응형 — 시각화 캔버스(스테이지)와 노드 잉크·툴팁·패널이 테마에 맞춰 재색칠(테마 전환 시 즉시 재렌더).
- **상관 분석 강화**: 네트워크 엣지를 NPMI 가중(굵기·투명도)으로 표시, **연관 임계 슬라이더**로 헤어볼 제어, **동시출현↔동시추세** 모드 전환, 엣지 호버 시 상관값. 엣지를 클릭하면 **AI가 그 상관 관계를 설명**(connect-the-dots).
- **상관 히트맵**: 상위 키워드 NxN 행렬을 색으로 — 상관을 *수치로* 바로 읽는 뷰(NPMI/동시추세 전환).
- **테마·KPI**: 다크/라이트 테마 토글, 상단 KPI 카드(기사·키워드·토픽군집·소스·감성 게이지).
- **색상 모드**: 네트워크/클라우드/버블을 분야·토픽군집·감성 기준으로 재색칠.
- **키워드 드릴다운**: 노드/트리맵 클릭 → 드로어(타임라인 스파크라인·연관 키워드·관련 기사).
- **인사이트·감성·내보내기**: 인사이트 스트립, 노드 툴팁·상태바 감성 표시, CSV 내보내기.
- **파워 기능**: 라이브 자동갱신, URL 해시로 상태 공유/복원, 키보드 단축키(`/` 검색 · `g` 생성 · `t` 테마 · `l` 언어 · `1–6` 뷰 · `Esc` 닫기).
- **키워드 검색**: 임의 키워드로 관련 뉴스를 실시간 검색해 사이드 패널에 목록 표시(제목·출처·링크), 원하면 트렌드 맵에 병합(`SEARCH` 분야로 표시). 검색 소스는 Google News 검색 + Tavily + **EODHD 금융뉴스**(질의가 티커형이면 `s=`, 아니면 `t=`태그로 조회).
- **뉴스 수 선택**: 사이드바 슬라이더로 소스·피드별 수집/검색 기사 수(10~100)를 조절(`per_feed`/`count` 파라미터).

## 환경변수

`.env.example` 참고. 주요 항목: `MYTREND_DATABASE_URL`(PostgreSQL DSN), `MYTREND_INGEST_INTERVAL_MIN`(기본 360=6시간), `MYTREND_ARTICLE_RETENTION_DAYS`(0=무제한), `MYTREND_DEFAULT_HOURS`, `MYTREND_PER_FEED_LIMIT`, `MYTREND_CACHE_TTL`, `MYTREND_INGEST_ON_START`, `MYTREND_AI_MODEL`. API 키(`TAVILY_API_KEY`/`EODHD_API_TOKEN`/`NEWSAPI_KEY`/`OPENROUTER_API_KEY`)는 `backend/.env`. **실제 키·비밀번호는 `.env`/`backend/.env`/`deploy.env`에만 두며 절대 커밋하지 않는다(`.gitignore` 처리됨).**

## Docker 실행

프론트엔드(nginx)와 백엔드(uvicorn)가 별도 컨테이너이고, **로컬(dev) compose는 PostgreSQL 컨테이너까지 함께** 띄운다(데이터는 named volume `mytrend_pgdata`). nginx가 공개 포트를 서빙하고 `/api/*`를 백엔드로 프록시한다.

```bash
cp .env.example .env     # 선택: 포트/키 설정
./manage.sh up           # db + backend + frontend 빌드·기동
# http://localhost:8000
```

`manage.sh` 명령:

| 명령 | 설명 |
|------|------|
| `up` / `down` / `restart` | 기동 / 중지 / 재시작 |
| `build` | 이미지 빌드 |
| `logs` | 로그 팔로우 |
| `status` | 컨테이너 + 헬스 상태 |
| `ingest` | 수동 즉시 수집 |
| `stats` | DB/스케줄러 상태 |
| `shell` | 백엔드 컨테이너 셸 |
| `psql` | PostgreSQL 셸 |
| `backup` | DB 덤프(`mytrend-backup-<날짜>.sql`) |
| `clean` | 컨테이너 + 볼륨(DB) 삭제 |
| `open` | 브라우저로 열기 |

> 운영(prod) 배포는 DB 컨테이너를 띄우지 않고 **서버의 기존 PostgreSQL** 에 접속한다. 자세한 내용은 [DEPLOY.md](DEPLOY.md) 참고.

## 원격 배포 (deploy.sh)

로컬 소스를 rsync로 원격 서버에 전송한 뒤 원격 Docker(`docker-compose.prod.yml`)에서 빌드·기동한다. 레지스트리 불필요. 서버의 기존 PostgreSQL을 사용하므로 서버 `.env`에 `MYTREND_DATABASE_URL`을 설정해야 한다.

```bash
cp deploy.env.example deploy.env   # 서버 주소/자격증명 입력
./deploy.sh            # 전송 → 원격 빌드/기동 → 헬스체크
./deploy.sh --no-build # 재빌드 없이 재기동만
./deploy.sh --logs     # 배포 후 로그 따라보기
```

- 인증: **SSH 키 우선**, 없으면 `deploy.env`의 `SERVER_PASSWORD`로 `sshpass` 비밀번호 인증(로컬에 `sshpass` 설치 필요).
- `deploy.env`(서버 비밀번호)와 `.env`/`backend/.env`(키·DB 자격증명)는 **반드시 커밋 금지**(`.gitignore` 처리됨). SSH 키 + `SERVER_PASSWORD` 공란을 권장.
- 원격 서버에는 `docker` + `docker compose` 플러그인과 접속 가능한 PostgreSQL이 미리 있어야 한다.
- 상세 절차·DB 준비·백업/이관은 [DEPLOY.md](DEPLOY.md) 참고.
