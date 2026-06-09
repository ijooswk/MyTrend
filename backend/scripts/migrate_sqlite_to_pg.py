#!/usr/bin/env python3
"""기존 SQLite(mytrend.db) → PostgreSQL 이관 (멱등).

articles 와 daily_keyword 를 그대로 옮긴다. 여러 번 실행해도 안전하다
(articles 는 id 충돌 시 갱신, daily_keyword 는 (day,keyword,region) 충돌 시 갱신).

사용 예 (백엔드 컨테이너 안에서 실행):
  # 1) 옛 SQLite 파일을 컨테이너로 복사해 두고
  docker compose -f docker-compose.prod.yml cp ./old-mytrend.db backend:/tmp/old.db
  # 2) 이관 실행 (대상 DSN 은 MYTREND_DATABASE_URL 환경변수 사용)
  docker compose -f docker-compose.prod.yml exec backend \
      python /app/backend/scripts/migrate_sqlite_to_pg.py --sqlite /tmp/old.db

로컬에서 직접 실행도 가능:
  python backend/scripts/migrate_sqlite_to_pg.py --sqlite backend/mytrend.db \
      --pg postgresql://mytrend:mytrend@localhost:5432/mytrend
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

import psycopg

# 스키마 정의 재사용(드리프트 방지). app 패키지가 import 가능한 환경에서 실행.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
try:
    from app.db import _SCHEMA_STMTS
except Exception:  # pragma: no cover - 독립 실행 폴백
    _SCHEMA_STMTS = None

ART_COLS = ["id", "title", "url", "source", "publisher", "category",
            "region", "lang", "published_at", "fetched_at", "summary"]
DK_COLS = ["day", "keyword", "region", "count", "sent_sum", "cat"]


def _table_exists(scon: sqlite3.Connection, name: str) -> bool:
    r = scon.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return r is not None


def _ensure_schema(pcon: psycopg.Connection) -> None:
    if not _SCHEMA_STMTS:
        print("⚠  app.db 스키마를 불러오지 못함 — 대상 PG 에 테이블이 이미 있어야 합니다.")
        return
    for stmt in _SCHEMA_STMTS:
        pcon.execute(stmt)
    pcon.commit()


def _migrate_articles(scon, pcon, batch: int) -> int:
    if not _table_exists(scon, "articles"):
        return 0
    cols = ",".join(ART_COLS)
    ph = ",".join(["%s"] * len(ART_COLS))
    upd = ",".join(f"{c}=EXCLUDED.{c}" for c in ART_COLS if c != "id")
    sql = (f"INSERT INTO articles ({cols}) VALUES ({ph}) "
           f"ON CONFLICT(id) DO UPDATE SET {upd}")
    total = 0
    cur = scon.execute(f"SELECT {cols} FROM articles")
    with pcon.cursor() as pc:
        while True:
            rows = cur.fetchmany(batch)
            if not rows:
                break
            pc.executemany(sql, [tuple(r) for r in rows])
            total += len(rows)
    pcon.commit()
    return total


def _migrate_daily(scon, pcon, batch: int) -> int:
    if not _table_exists(scon, "daily_keyword"):
        return 0
    cols = ",".join(DK_COLS)
    ph = ",".join(["%s"] * len(DK_COLS))
    upd = ",".join(f"{c}=EXCLUDED.{c}" for c in DK_COLS
                   if c not in ("day", "keyword", "region"))
    sql = (f"INSERT INTO daily_keyword ({cols}) VALUES ({ph}) "
           f"ON CONFLICT(day,keyword,region) DO UPDATE SET {upd}")
    total = 0
    cur = scon.execute(f"SELECT {cols} FROM daily_keyword")
    with pcon.cursor() as pc:
        while True:
            rows = cur.fetchmany(batch)
            if not rows:
                break
            pc.executemany(sql, [tuple(r) for r in rows])
            total += len(rows)
    pcon.commit()
    return total


def main() -> int:
    ap = argparse.ArgumentParser(description="SQLite → PostgreSQL 이관")
    ap.add_argument("--sqlite", required=True, help="원본 SQLite 파일 경로")
    ap.add_argument("--pg", default=os.environ.get("MYTREND_DATABASE_URL"),
                    help="대상 PostgreSQL DSN (기본: $MYTREND_DATABASE_URL)")
    ap.add_argument("--batch", type=int, default=1000, help="배치 크기")
    args = ap.parse_args()

    if not args.pg:
        print("‼  대상 DSN 이 없습니다. --pg 또는 MYTREND_DATABASE_URL 을 지정하세요.")
        return 2
    if not os.path.exists(args.sqlite):
        print(f"‼  SQLite 파일을 찾을 수 없음: {args.sqlite}")
        return 2

    scon = sqlite3.connect(args.sqlite)
    with psycopg.connect(args.pg) as pcon:
        _ensure_schema(pcon)
        n_art = _migrate_articles(scon, pcon, args.batch)
        n_dk = _migrate_daily(scon, pcon, args.batch)
    scon.close()

    print(f"✅ 이관 완료 — articles {n_art}건, daily_keyword {n_dk}건")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
