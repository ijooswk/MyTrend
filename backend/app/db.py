"""SQLite 데이터 계층: 기사 저장/조회."""
from __future__ import annotations

import hashlib
import sqlite3
import threading
import time
from dataclasses import dataclass, asdict
from typing import Iterable, Optional

_LOCK = threading.Lock()


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


_SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id           TEXT PRIMARY KEY,
    title        TEXT NOT NULL,
    url          TEXT,
    source       TEXT,
    publisher    TEXT,
    category     TEXT,
    region       TEXT,
    lang         TEXT,
    published_at REAL,
    fetched_at   REAL,
    summary      TEXT
);
CREATE INDEX IF NOT EXISTS idx_published ON articles(published_at);
CREATE INDEX IF NOT EXISTS idx_cat_region ON articles(category, region);

-- 일별 키워드 롤업(장기 보존). 원시 기사는 프루닝돼도 이 집계는 영구 유지.
CREATE TABLE IF NOT EXISTS daily_keyword (
    day       TEXT NOT NULL,       -- YYYY-MM-DD (UTC)
    keyword   TEXT NOT NULL,
    region    TEXT NOT NULL,
    count     INTEGER NOT NULL,    -- 해당 일·지역에서 키워드가 등장한 기사 수
    sent_sum  REAL NOT NULL,       -- 감성 점수 합(평균은 sent_sum/count)
    cat       TEXT,                -- 우세 분야
    PRIMARY KEY (day, keyword, region)
);
CREATE INDEX IF NOT EXISTS idx_dk_keyword ON daily_keyword(keyword);
CREATE INDEX IF NOT EXISTS idx_dk_day ON daily_keyword(day);
"""


class DB:
    def __init__(self, path: str):
        self.path = path
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with _LOCK:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def upsert_many(self, articles: Iterable[Article]) -> int:
        rows = [
            (a.id, a.title, a.url, a.source, a.publisher, a.category,
             a.region, a.lang, a.published_at, a.fetched_at, a.summary)
            for a in articles
        ]
        if not rows:
            return 0
        with _LOCK:
            cur = self._conn.executemany(
                """INSERT INTO articles
                   (id,title,url,source,publisher,category,region,lang,published_at,fetched_at,summary)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET
                     fetched_at=excluded.fetched_at,
                     summary=CASE WHEN excluded.summary!='' THEN excluded.summary ELSE articles.summary END
                """, rows)
            self._conn.commit()
            return cur.rowcount

    def query(self, *, since: float, categories: Optional[list[str]] = None,
              regions: Optional[list[str]] = None, sources: Optional[list[str]] = None,
              limit: int = 5000) -> list[Article]:
        sql = "SELECT * FROM articles WHERE published_at >= ?"
        params: list = [since]
        if categories:
            sql += f" AND category IN ({','.join('?'*len(categories))})"
            params += categories
        if regions:
            sql += f" AND region IN ({','.join('?'*len(regions))})"
            params += regions
        if sources:
            sql += f" AND source IN ({','.join('?'*len(sources))})"
            params += sources
        sql += " ORDER BY published_at DESC LIMIT ?"
        params.append(limit)
        with _LOCK:
            rows = self._conn.execute(sql, params).fetchall()
        return [Article(**dict(r)) for r in rows]

    def query_between(self, start: float, end: float,
                      regions: Optional[list[str]] = None) -> list[Article]:
        """[start, end) 발행 기사."""
        sql = "SELECT * FROM articles WHERE published_at >= ? AND published_at < ?"
        params: list = [start, end]
        if regions:
            sql += f" AND region IN ({','.join('?'*len(regions))})"
            params += regions
        with _LOCK:
            rows = self._conn.execute(sql, params).fetchall()
        return [Article(**dict(r)) for r in rows]

    # ── 일별 롤업 ──
    def replace_daily(self, day: str, rows: list[tuple]) -> int:
        """특정 날짜의 롤업을 통째로 교체(멱등). rows=(day,keyword,region,count,sent_sum,cat)."""
        with _LOCK:
            self._conn.execute("DELETE FROM daily_keyword WHERE day = ?", (day,))
            if rows:
                self._conn.executemany(
                    "INSERT INTO daily_keyword (day,keyword,region,count,sent_sum,cat) "
                    "VALUES (?,?,?,?,?,?)", rows)
            self._conn.commit()
            return len(rows)

    def daily_series(self, keyword: str, *, since_day: str, until_day: str,
                     regions: Optional[list[str]] = None) -> list[tuple]:
        """키워드의 일별 (day, count, sent_sum) 시계열."""
        sql = ("SELECT day, SUM(count) c, SUM(sent_sum) s FROM daily_keyword "
               "WHERE keyword = ? AND day >= ? AND day <= ?")
        params: list = [keyword, since_day, until_day]
        if regions:
            sql += f" AND region IN ({','.join('?'*len(regions))})"
            params += regions
        sql += " GROUP BY day ORDER BY day"
        with _LOCK:
            return [(r["day"], r["c"], r["s"]) for r in self._conn.execute(sql, params).fetchall()]

    def daily_all(self, *, since_day: str, until_day: str,
                  regions: Optional[list[str]] = None) -> list[tuple]:
        """기간 내 모든 (day, keyword, count, sent_sum, cat) — 돌발/계절성 분석용."""
        sql = ("SELECT day, keyword, SUM(count) c, SUM(sent_sum) s, "
               "MAX(cat) cat FROM daily_keyword WHERE day >= ? AND day <= ?")
        params: list = [since_day, until_day]
        if regions:
            sql += f" AND region IN ({','.join('?'*len(regions))})"
            params += regions
        sql += " GROUP BY day, keyword"
        with _LOCK:
            return [(r["day"], r["keyword"], r["c"], r["s"], r["cat"])
                    for r in self._conn.execute(sql, params).fetchall()]

    def daily_day_bounds(self) -> tuple:
        with _LOCK:
            r = self._conn.execute("SELECT MIN(day) lo, MAX(day) hi, COUNT(*) n FROM daily_keyword").fetchone()
        return (r["lo"], r["hi"], r["n"])

    def article_time_bounds(self) -> tuple:
        with _LOCK:
            r = self._conn.execute("SELECT MIN(published_at) lo, MAX(published_at) hi FROM articles").fetchone()
        return (r["lo"], r["hi"])

    def stats(self) -> dict:
        with _LOCK:
            total = self._conn.execute("SELECT COUNT(*) c FROM articles").fetchone()["c"]
            newest = self._conn.execute("SELECT MAX(fetched_at) m FROM articles").fetchone()["m"]
            by_src = self._conn.execute(
                "SELECT source, COUNT(*) c FROM articles GROUP BY source").fetchall()
            by_cat = self._conn.execute(
                "SELECT category, COUNT(*) c FROM articles GROUP BY category").fetchall()
        return {
            "total": total,
            "last_fetch": newest,
            "by_source": {r["source"]: r["c"] for r in by_src},
            "by_category": {r["category"]: r["c"] for r in by_cat},
        }

    def prune(self, older_than_days: int = 7) -> int:
        cutoff = time.time() - older_than_days * 86400
        with _LOCK:
            cur = self._conn.execute("DELETE FROM articles WHERE published_at < ?", (cutoff,))
            self._conn.commit()
            return cur.rowcount
