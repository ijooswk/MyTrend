"""PostgreSQL 데이터 계층: 기사 저장/조회 + 일별 키워드 롤업.

psycopg3 + 커넥션 풀 사용. 외부 모듈은 DB 클래스 메서드와 Article 만 사용한다.
접속 문자열(DSN) 예: postgresql://mytrend:secret@db:5432/mytrend
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Iterable, Optional

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool


@dataclass
class Article:
    id: str
    title: str
    url: str
    source: str          # 수집 소스 (google_news / tavily / eodhd / rss / newsapi)
    publisher: str       # 언론사명
    category: str        # BUSINESS / NATION / SCIENCE / TECHNOLOGY / WORLD
    region: str          # KR / US
    lang: str            # ko / en
    published_at: float  # epoch seconds
    fetched_at: float
    summary: str = ""

    @staticmethod
    def make_id(url: str, title: str) -> str:
        key = (url or "").strip() or title.strip()
        return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


# 스키마는 멱등(IF NOT EXISTS). 시작 시 1회 적용.
_SCHEMA_STMTS = [
    """
    CREATE TABLE IF NOT EXISTS articles (
        id           TEXT PRIMARY KEY,
        title        TEXT NOT NULL,
        url          TEXT,
        source       TEXT,
        publisher    TEXT,
        category     TEXT,
        region       TEXT,
        lang         TEXT,
        published_at DOUBLE PRECISION,
        fetched_at   DOUBLE PRECISION,
        summary      TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_published ON articles(published_at)",
    "CREATE INDEX IF NOT EXISTS idx_cat_region ON articles(category, region)",
    # 일별 키워드 롤업(장기 보존). 원시 기사가 프루닝돼도 이 집계는 영구 유지.
    """
    CREATE TABLE IF NOT EXISTS daily_keyword (
        day       TEXT NOT NULL,             -- YYYY-MM-DD (UTC)
        keyword   TEXT NOT NULL,
        region    TEXT NOT NULL,
        count     INTEGER NOT NULL,          -- 해당 일·지역에서 키워드가 등장한 기사 수
        sent_sum  DOUBLE PRECISION NOT NULL, -- 감성 점수 합(평균은 sent_sum/count)
        cat       TEXT,                      -- 우세 분야
        PRIMARY KEY (day, keyword, region)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_dk_keyword ON daily_keyword(keyword)",
    "CREATE INDEX IF NOT EXISTS idx_dk_day ON daily_keyword(day)",
]


def _in_clause(col: str, values: list, params: list) -> str:
    """col IN (%s,%s,...) 절을 만들고 params 에 값을 추가."""
    params.extend(values)
    return f" AND {col} IN ({','.join(['%s'] * len(values))})"


class DB:
    """PostgreSQL 데이터 계층. dsn 으로 커넥션 풀을 연다."""

    def __init__(self, dsn: str, *, min_size: int = 1, max_size: int = 10):
        self.dsn = dsn
        self.pool = ConnectionPool(
            dsn, min_size=min_size, max_size=max_size, open=True,
            kwargs={"row_factory": dict_row},
        )
        self.pool.wait(timeout=15)
        self._init_schema()

    def _init_schema(self) -> None:
        with self.pool.connection() as conn:
            for stmt in _SCHEMA_STMTS:
                conn.execute(stmt)

    def close(self) -> None:
        self.pool.close()

    # ── 기사 ──
    def upsert_many(self, articles: Iterable[Article]) -> int:
        rows = [
            (a.id, a.title, a.url, a.source, a.publisher, a.category,
             a.region, a.lang, a.published_at, a.fetched_at, a.summary)
            for a in articles
        ]
        if not rows:
            return 0
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO articles
                   (id,title,url,source,publisher,category,region,lang,published_at,fetched_at,summary)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT(id) DO UPDATE SET
                     fetched_at=EXCLUDED.fetched_at,
                     summary=CASE WHEN EXCLUDED.summary <> '' THEN EXCLUDED.summary
                                  ELSE articles.summary END
                """, rows)
        return len(rows)

    def query(self, *, since: float, categories: Optional[list[str]] = None,
              regions: Optional[list[str]] = None, sources: Optional[list[str]] = None,
              limit: int = 5000) -> list[Article]:
        sql = "SELECT * FROM articles WHERE published_at >= %s"
        params: list = [since]
        if categories:
            sql += _in_clause("category", categories, params)
        if regions:
            sql += _in_clause("region", regions, params)
        if sources:
            sql += _in_clause("source", sources, params)
        sql += " ORDER BY published_at DESC LIMIT %s"
        params.append(limit)
        with self.pool.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [Article(**r) for r in rows]

    def query_between(self, start: float, end: float,
                      regions: Optional[list[str]] = None) -> list[Article]:
        """[start, end) 발행 기사."""
        sql = "SELECT * FROM articles WHERE published_at >= %s AND published_at < %s"
        params: list = [start, end]
        if regions:
            sql += _in_clause("region", regions, params)
        with self.pool.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [Article(**r) for r in rows]

    # ── 일별 롤업 ──
    def replace_daily(self, day: str, rows: list[tuple]) -> int:
        """특정 날짜의 롤업을 통째로 교체(멱등). rows=(day,keyword,region,count,sent_sum,cat)."""
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM daily_keyword WHERE day = %s", (day,))
            if rows:
                cur.executemany(
                    "INSERT INTO daily_keyword (day,keyword,region,count,sent_sum,cat) "
                    "VALUES (%s,%s,%s,%s,%s,%s)", rows)
        return len(rows)

    def daily_series(self, keyword: str, *, since_day: str, until_day: str,
                     regions: Optional[list[str]] = None) -> list[tuple]:
        """키워드의 일별 (day, count, sent_sum) 시계열."""
        sql = ("SELECT day, SUM(count) AS c, SUM(sent_sum) AS s FROM daily_keyword "
               "WHERE keyword = %s AND day >= %s AND day <= %s")
        params: list = [keyword, since_day, until_day]
        if regions:
            sql += _in_clause("region", regions, params)
        sql += " GROUP BY day ORDER BY day"
        with self.pool.connection() as conn:
            return [(r["day"], r["c"], r["s"])
                    for r in conn.execute(sql, params).fetchall()]

    def daily_all(self, *, since_day: str, until_day: str,
                  regions: Optional[list[str]] = None) -> list[tuple]:
        """기간 내 모든 (day, keyword, count, sent_sum, cat) — 돌발/계절성 분석용."""
        sql = ("SELECT day, keyword, SUM(count) AS c, SUM(sent_sum) AS s, "
               "MAX(cat) AS cat FROM daily_keyword WHERE day >= %s AND day <= %s")
        params: list = [since_day, until_day]
        if regions:
            sql += _in_clause("region", regions, params)
        sql += " GROUP BY day, keyword"
        with self.pool.connection() as conn:
            return [(r["day"], r["keyword"], r["c"], r["s"], r["cat"])
                    for r in conn.execute(sql, params).fetchall()]

    def daily_day_bounds(self) -> tuple:
        with self.pool.connection() as conn:
            r = conn.execute(
                "SELECT MIN(day) AS lo, MAX(day) AS hi, COUNT(*) AS n FROM daily_keyword"
            ).fetchone()
        return (r["lo"], r["hi"], r["n"])

    def article_time_bounds(self) -> tuple:
        with self.pool.connection() as conn:
            r = conn.execute(
                "SELECT MIN(published_at) AS lo, MAX(published_at) AS hi FROM articles"
            ).fetchone()
        return (r["lo"], r["hi"])

    def stats(self) -> dict:
        with self.pool.connection() as conn:
            total = conn.execute("SELECT COUNT(*) AS c FROM articles").fetchone()["c"]
            newest = conn.execute("SELECT MAX(fetched_at) AS m FROM articles").fetchone()["m"]
            by_src = conn.execute(
                "SELECT source, COUNT(*) AS c FROM articles GROUP BY source").fetchall()
            by_cat = conn.execute(
                "SELECT category, COUNT(*) AS c FROM articles GROUP BY category").fetchall()
        return {
            "total": total,
            "last_fetch": newest,
            "by_source": {r["source"]: r["c"] for r in by_src},
            "by_category": {r["category"]: r["c"] for r in by_cat},
        }

    def prune(self, older_than_days: int = 7) -> int:
        if older_than_days <= 0:
            return 0  # 보존 무제한 — 원시 기사를 영구 보관(장기 분석용)
        cutoff = time.time() - older_than_days * 86400
        with self.pool.connection() as conn:
            cur = conn.execute("DELETE FROM articles WHERE published_at < %s", (cutoff,))
            return cur.rowcount
