# MyTrend — 뉴스 키워드 트렌드 맵

최근 24시간 뉴스를 여러 소스에서 수집해 키워드를 추출하고, 분야별 트렌드 맵(키워드 네트워크 · 워드클라우드 · 분야별 버블)으로 시각화하는 풀스택 앱.

## 구성

```
MyTrend/
├── backend/                # Python + FastAPI
│   ├── app/
│   │   ├── main.py         # FastAPI 라우트 + 정적 서빙
│   │   ├── config.py       # 분야·지역·소스·환경설정
│   │   ├── db.py           # SQLite 데이터 계층
│   │   ├── nlp.py          # 키워드 추출(kiwi/휴리스틱) + 트렌드 분석
│   │   ├── ingest.py       # 전 소스 병렬 수집 오케스트레이션
│   │   ├── trends.py       # 캐시 + 미스 시 실시간 보완
│   │   ├── scheduler.py    # APScheduler 주기 수집
│   │   └── sources/        # 소스 어댑터
│   │       ├── google_news.py   # Google News RSS (키 불필요)
│   │       ├── generic_rss.py   # BBC·연합·한겨레 등 (키 불필요)
│   │       ├── tavily.py        # Tavily 검색 API
│   │       ├── eodhd.py         # EODHD 금융뉴스 API
│   │       └── newsapi.py       # NewsAPI.org
│   ├── requirements.txt
│   ├── .env.example
│   └── run.sh
├── frontend/
│   └── index.html          # D3 기반 시각화 UI (API 소비)
└── trendmap.html           # (참고) 백엔드 없이 동작하는 단독 버전
```

## 실행

```bash
cd backend
bash run.sh          # venv 생성 → 의존성 설치 → .env 생성 → uvicorn 실행
```

브라우저에서 http://localhost:8000 접속.

수동 실행:

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # 필요 시 API 키 입력
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

- **스케줄러**: 시작 시 1회 + `MYTREND_INGEST_INTERVAL_MIN`(기본 20분)마다 전 소스 수집 → SQLite 적재. 매일 04시 7일 지난 기사 정리.
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
- **감성 분석**: 한/영 극성 사전으로 제목 감성 점수(-1~+1) 산출 → 키워드·분야·전체 평균 감성 제공.
- **급상승(모멘텀)**: 시간창을 절반으로 나눠 최근 급증 키워드를 탐지(신규 부상 `NEW` 표시).
- **토픽 군집**: 동시출현 그래프 라벨 전파(label propagation)로 키워드를 테마 군집으로 묶음.
- **자동 인사이트**: 최다 분야·급상승·허브 키워드·전반 감성·핵심 토픽을 구조화해 제공(프론트에서 다국어 렌더).
- **타임라인**: 키워드별 시간대별 빈도 시계열(스파크라인·드릴다운).
- **내보내기**: 키워드·빈도·분야·감성·연결수·대표기사를 CSV/JSON 으로 추출해 다른 도구/분야에서 재사용.

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
pytest -q
```

`tests/` 에 키워드 추출(영문 회귀 포함)·복합명사·감성·모멘텀·DB·검색 라우팅·API 스모크 테스트 수록.

## 프론트엔드 기능

- **지역 토글**: 상단에서 한국 / 글로벌 / 통합 전환.
- **다국어**: 한국어 ↔ 영어 UI 전환(선택값은 브라우저에 저장).
- **5종 뷰 + 급상승**: 키워드 네트워크, 워드클라우드, 분야별 버블, **트리맵**, 급상승 키워드(증가율·NEW 배지).
- **테마·KPI**: 다크/라이트 테마 토글, 상단 KPI 카드(기사·키워드·토픽군집·소스·감성 게이지).
- **색상 모드**: 네트워크/클라우드/버블을 분야·토픽군집·감성 기준으로 재색칠.
- **키워드 드릴다운**: 노드/트리맵 클릭 → 드로어(타임라인 스파크라인·연관 키워드·관련 기사).
- **인사이트·감성·내보내기**: 인사이트 스트립, 노드 툴팁·상태바 감성 표시, CSV 내보내기.
- **파워 기능**: 라이브 자동갱신, URL 해시로 상태 공유/복원, 키보드 단축키(`/` 검색 · `g` 생성 · `t` 테마 · `l` 언어 · `1–6` 뷰 · `Esc` 닫기).
- **키워드 검색**: 임의 키워드로 관련 뉴스를 실시간 검색해 사이드 패널에 목록 표시(제목·출처·링크), 원하면 트렌드 맵에 병합(`SEARCH` 분야로 표시). 검색 소스는 Google News 검색 + Tavily + **EODHD 금융뉴스**(질의가 티커형이면 `s=`, 아니면 `t=`태그로 조회).
- **뉴스 수 선택**: 사이드바 슬라이더로 소스·피드별 수집/검색 기사 수(10~100)를 조절(`per_feed`/`count` 파라미터).

## 환경변수

`.env.example` 참고. 주요 항목: `MYTREND_INGEST_INTERVAL_MIN`, `MYTREND_DEFAULT_HOURS`, `MYTREND_PER_FEED_LIMIT`, `MYTREND_CACHE_TTL`, `MYTREND_INGEST_ON_START`.

## Docker 실행

단일 컨테이너가 API와 프론트엔드를 함께 서빙하며, SQLite는 named volume(`mytrend_data`)에 영속된다.

```bash
cp .env.example .env     # 선택: 포트/키 설정
./manage.sh up           # 빌드 후 백그라운드 기동
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
| `shell` | 컨테이너 셸 |
| `clean` | 컨테이너 + 볼륨(DB) 삭제 |
| `open` | 브라우저로 열기 |

## 원격 배포 (deploy.sh)

로컬 소스를 원격 서버로 전송한 뒤 원격 Docker에서 빌드·기동한다. 레지스트리 불필요.

```bash
cp deploy.env.example deploy.env   # 서버/자격증명 입력 (이미 채워져 있으면 생략)
./deploy.sh up        # 전송 → 원격 빌드/기동 → http://<REMOTE_HOST>:<PORT>
./deploy.sh status    # 원격 상태/헬스
./deploy.sh logs      # 원격 로그
./deploy.sh down      # 원격 중지
```

- 인증: **SSH 키 우선**, 없으면 `deploy.env`의 `REMOTE_PASS`로 `sshpass` 비밀번호 인증(로컬에 `sshpass` 설치 필요).
- `deploy.env`에는 비밀번호가 들어가므로 **반드시 커밋 금지**(`.gitignore`에 포함됨). 운영 환경에서는 비밀번호 대신 SSH 키 + `REMOTE_PASS` 공란을 권장.
- 원격 서버에는 `docker` + `docker compose` 플러그인이 미리 설치돼 있어야 한다(스크립트가 점검 후 안내).
