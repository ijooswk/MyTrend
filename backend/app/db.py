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
