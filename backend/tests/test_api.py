"""DB·검색 라우팅·API 엔드포인트 테스트."""
import os
import time

os.environ.setdefault("MYTREND_INGEST_ON_START", "false")
os.environ.setdefault("MYTREND_INGEST_INTERVAL_MIN", "0")
os.environ["MYTREND_DB_PATH"] = ":memory:"

from app.db import DB, Article
from app.search import eodhd_query_mode


def test_db_upsert_dedup_and_query():
    db = DB(":memory:")
    now = time.time()
    a = Article(id="x1", title="t", url="u", source="rss", publisher="p",
                category="TECHNOLOGY", region="KR", lang="ko",
                published_at=now, fetched_at=now)
    db.upsert_many([a])
    db.upsert_many([a])                      # 중복 → 1건 유지
    rows = db.query(since=now - 3600)
    assert len(rows) == 1
    assert db.query(since=now - 3600, categories=["BUSINESS"]) == []


def test_eodhd_key_coalesce_docker_scenario():
    # Docker 가 빈 EODHD_API_KEY 를 주입해도 EODHD_API_TOKEN 으로 폴백해야 함(회귀 방지)
    from app.config import Settings
    assert Settings(eodhd_api_key="", eodhd_api_token="tok123").eodhd_key == "tok123"
    assert Settings(eodhd_api_key="key456", eodhd_api_token="").eodhd_key == "key456"
    assert Settings(eodhd_api_key="key456", eodhd_api_token="tok123").eodhd_key == "key456"
    assert Settings(eodhd_api_key="", eodhd_api_token="").eodhd_key == ""


def test_eodhd_query_mode_ticker_vs_tag():
    assert eodhd_query_mode("AAPL") == "s"
    assert eodhd_query_mode("TSLA.US") == "s"
    assert eodhd_query_mode("AI") == "s"
    assert eodhd_query_mode("artificial intelligence") == "t"   # 공백 → 태그
    assert eodhd_query_mode("삼성전자") == "t"                   # 비ASCII → 태그


def test_endpoints_smoke():
    from fastapi.testclient import TestClient
    from app import main as m
    with TestClient(m.app) as c:
        assert c.get("/api/health").json() == {"ok": True}
        cfg = c.get("/api/config").json()
        ids = [x["id"] for x in cfg["categories"]]
        assert {"BUSINESS", "HEALTH", "SPORTS", "ENTERTAINMENT", "SEARCH"} <= set(ids)
        # 트렌드(live=false, 빈 DB) 200
        assert c.get("/api/trends", params={"categories": ["TECHNOLOGY"],
                     "regions": ["KR"], "live": "false"}).status_code == 200
        # 내보내기 CSV 200
        r = c.get("/api/export", params={"fmt": "csv", "live": "false"})
        assert r.status_code == 200 and "keyword" in r.text
        # 타임라인 200 + 스키마
        tl = c.get("/api/timeline", params={"hours": 24, "buckets": 12}).json()
        assert len(tl["buckets"]) == 12 and "series" in tl and "total" in tl
        # 상관 행렬 200 + 스키마(빈 DB → 빈 행렬)
        cor = c.get("/api/correlation", params={"metric": "npmi", "top": 10}).json()
        assert cor["metric"] == "npmi" and "matrix" in cor and "keywords" in cor
        # 장기 분석 엔드포인트(빈 DB에서도 스키마 유효)
        assert c.post("/api/rollup").status_code == 200
        h = c.get("/api/history", params={"keyword": "AI", "days": 30}).json()
        assert h["keyword"] == "AI" and "points" in h
        assert "breakouts" in c.get("/api/breakouts").json()
        assert "cycles" in c.get("/api/seasonality", params={"keyword": "AI"}).json()
