# 배포 가이드 (Docker · 원격 서버)

원격 서버 `100.98.178.217` 에 Docker 로 배포한다. MyTrend 는 **2개 컨테이너**로 구성된다: `frontend`(nginx) 가 정적 SPA 를 서빙하며 공개 포트(`19090`)에 바인딩하고 `/api/*` 요청을 `backend`(FastAPI/uvicorn, 내부 `127.0.0.1:8001`)로 프록시한다. 외부 진입점은 nginx 포트 하나(`19090`)뿐이며 백엔드는 외부로 노출되지 않는다. 두 컨테이너 모두 `network_mode: host`(Meshnet 회피)로 동작하고, SQLite DB 는 named volume `mytrend_data` 에 영속된다.

## 사전 준비 (최초 1회)

1. **로컬에 sshpass**(비밀번호 자동 입력용, 선택) 또는 **SSH 키 등록**(권장):
   ```bash
   ssh-copy-id sehun@100.98.178.217          # 키 등록 시 비밀번호 불필요
   # 또는: brew install hudochenkov/sshpass/sshpass
   ```
2. **서버에 Docker**(없으면 deploy.sh 가 안내):
   ```bash
   ssh sehun@100.98.178.217
   curl -fsSL https://get.docker.com | sh
   sudo usermod -aG docker sehun             # 재로그인 필요
   ```
3. **배포 설정**: `cp deploy.env.example deploy.env` 후 값 확인(이미 채워져 있으면 생략). `deploy.env` 는 gitignore 된다.

## 배포

로컬 프로젝트 루트에서:
```bash
./deploy.sh
```
- 소스를 서버 `/home/sehun/mytrend` 로 rsync(`.git`/`.venv`/`*.db`/`data` 등 제외, **`backend/.env`(API 키)는 함께 전송**)
- 서버에서 `docker compose -f docker-compose.prod.yml up -d --build`
- `/api/health` 헬스체크

옵션:
```bash
./deploy.sh --no-build   # 코드만 동기화 후 재기동
./deploy.sh --logs       # 배포 후 로그 follow
```

서버/계정은 `deploy.env` 또는 환경변수로 덮어쓸 수 있다:
```bash
SERVER_IP=1.2.3.4 SERVER_USER=ubuntu ./deploy.sh
```

## 접속

- 앱(프론트+API): `http://100.98.178.217:19090`
- API 문서:        `http://100.98.178.217:19090/docs`

> 서버에 이미 다른 스택들이 80/8000/18000/18080/19000/19080 등을 쓰고 있어, 겹치지 않는 **19090** 으로 지정했다. 변경은 서버 `.env` 의 `MYTREND_PORT`.

### NordVPN Meshnet + Docker 접근 (중요)

서버가 NordVPN Meshnet(100.x) 뒤에 있으면, Docker 가 공개 포트를 컨테이너의 `172.x` 브리지로 포워딩하는데 Meshnet 이 그 트래픽을 "로컬 네트워크"로 보고 **드롭**한다. 그래서 SSH(22, 호스트 직결)는 되는데 컨테이너 웹 포트는 안 되는 현상이 생긴다.

해결: `docker-compose.prod.yml` 에서 **`network_mode: host`** 로 두어 uvicorn 이 호스트 인터페이스에 직접 바인딩(`--port 19090`)하게 했다(SSH 와 동일 경로 → Meshnet 차단 없음). host 모드라 `ports:` 는 무시되고 공개 포트는 `MYTREND_PORT` 가 결정한다.

## 환경변수

| 파일 | 내용 | 비고 |
|------|------|------|
| `backend/.env` | EODHD / OpenRouter / Tavily API 키 | rsync 로 함께 전송됨(gitignore) |
| `.env` (서버) | 포트·동작·보존정책 (`MYTREND_*`) | 없으면 `.env.prod.example` 에서 자동 생성 |
| `deploy.env` (로컬) | 서버 IP/계정/비밀번호 | 배포에만 사용(gitignore) |

## 데이터 영속 & 보존

- SQLite + 일별 롤업은 named volume `mytrend_data` 에 저장된다. **rsync `--delete` 의 영향을 받지 않으므로** 재배포해도 누적 데이터가 보존된다.
- 원시 기사는 `MYTREND_ARTICLE_RETENTION_DAYS`(기본 120일) 후 프루닝되지만 일별 롤업(`daily_keyword`)은 영구 보존된다.
- **최초 배포 후 1회** 기존 기사를 롤업으로 백필:
  ```bash
  curl -X POST http://100.98.178.217:19090/api/rollup
  ```

## 운영 명령 (서버에서)

```bash
cd ~/mytrend
docker compose -f docker-compose.prod.yml ps              # 상태
docker compose -f docker-compose.prod.yml logs -f         # 로그
docker compose -f docker-compose.prod.yml restart         # 재시작
docker compose -f docker-compose.prod.yml down            # 중지
```

## 보안 참고

- 비밀번호는 `deploy.env`(gitignore)에 두며, 가능하면 SSH 키 인증으로 전환하고 `SERVER_PASSWORD` 를 비운다.
- API 키는 `backend/.env`(gitignore)로만 관리하며 저장소에 커밋하지 않는다.
- 외부 노출 시 방화벽에서 `19090` 포트 정책을 확인한다.
