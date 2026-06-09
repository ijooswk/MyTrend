"""pytest 공용 설정.

DB 가 필요한 테스트는 @pytest.mark.pg 로 표시한다. PostgreSQL 테스트 DB 가
없으면(MYTREND_TEST_DATABASE_URL 미설정 또는 접속 불가) 해당 테스트는 자동 skip 되고,
DB 비의존 테스트(nlp/assoc/순수 함수)는 그대로 실행된다.

테스트 DB 지정 예:
  MYTREND_TEST_DATABASE_URL=postgresql://mytrend:mytrend@localhost:5432/mytrend_test pytest
"""
import os

os.environ.setdefault("MYTREND_INGEST_ON_START", "false")
os.environ.setdefault("MYTREND_INGEST_INTERVAL_MIN", "0")

import pytest

_PG_URL = os.environ.get("MYTREND_TEST_DATABASE_URL") or os.environ.get("MYTREND_DATABASE_URL")
if _PG_URL:
    # 앱이 동일 DB 를 쓰도록 강제(app 의 기본 DSN 대신 테스트 DSN 사용).
    os.environ["MYTREND_DATABASE_URL"] = _PG_URL


def _pg_available(url: str | None) -> bool:
    if not url:
        return False
    try:
        import psycopg
        with psycopg.connect(url, connect_timeout=3) as c:
            c.execute("SELECT 1")
        return True
    except Exception:
        return False


_PG_OK = _pg_available(_PG_URL)


def pytest_configure(config):
    config.addinivalue_line("markers", "pg: PostgreSQL 테스트 DB 가 필요한 테스트")


def pytest_collection_modifyitems(config, items):
    if _PG_OK:
        return
    skip = pytest.mark.skip(
        reason="PostgreSQL 테스트 DB 없음 — MYTREND_TEST_DATABASE_URL 설정 후 실행")
    for item in items:
        if "pg" in item.keywords:
            item.add_marker(skip)


def _reset_tables() -> None:
    import psycopg
    with psycopg.connect(_PG_URL, autocommit=True) as c:
        for tbl in ("articles", "daily_keyword"):
            try:
                c.execute(f"TRUNCATE {tbl}")
            except Exception:
                pass  # 스키마가 아직 없으면 무시(곧 DB() 가 생성)


@pytest.fixture
def db():
    """깨끗한 스키마의 DB 인스턴스. 테스트마다 테이블 비움."""
    from app.db import DB
    d = DB(_PG_URL)        # 스키마 보장(멱등)
    _reset_tables()
    yield d
    d.close()


@pytest.fixture(autouse=True)
def _clean_pg(request):
    """pg 마커 테스트는 본문 실행 전에 스키마 보장 + 테이블 정리."""
    if _PG_OK and request.node.get_closest_marker("pg"):
        from app.db import DB
        DB(_PG_URL).close()   # 스키마 보장
        _reset_tables()
    yield
