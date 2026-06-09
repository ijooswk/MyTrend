"""장기 누적 분석(롤업·히스토리·돌발·계절성) 테스트."""
import time

import pytest

from app.db import Article
from app import history as H

pytestmark = pytest.mark.pg


def test_rollup_day_aggregates(db):
    day = "2026-06-01"
    start, _ = H.day_bounds(day)
    db.upsert_many([Article(id=str(i), title=t, url="u", source="s", publisher="p",
                            category="TECHNOLOGY", region="KR", lang="ko",
                            published_at=start + 3600, fetched_at=start, summary="")
                    for i, t in enumerate(["삼성전자 AI 반도체 급등", "엔비디아 AI 반도체"])])
    H.rollup_day(db, day)
    ser = db.daily_series("AI", since_day="2026-05-01", until_day="2026-06-30")
    assert ser == [("2026-06-01", 2, ser[0][2])]   # AI 2건
    # 멱등성: 다시 롤업해도 중복 누적 안 됨
    H.rollup_day(db, day)
    assert db.daily_series("AI", since_day="2026-05-01", until_day="2026-06-30")[0][1] == 2


def test_query_history_week_month_buckets(db):
    for i, d in enumerate(["2025-01-06", "2025-01-07", "2025-02-10"]):
        db.replace_daily(d, [(d, "kw", "KR", i + 1, 0.0, "T")])
    wk = H.query_history(db, "kw", since_day="2025-01-01", until_day="2025-03-01", interval="week")
    mo = H.query_history(db, "kw", since_day="2025-01-01", until_day="2025-03-01", interval="month")
    assert wk["points"][0]["count"] == 3       # 1/6, 1/7 같은 주(월요일 기준) → 1+2
    assert {p["period"] for p in mo["points"]} == {"2025-01", "2025-02"}


def test_detect_breakouts(db):
    asof = "2025-12-31"
    # baseline 변동(0~2), 최근 7일 급증(15)
    for i in range(90):
        d = H.day_add(asof, -i)
        cnt = 15 if i < 7 else (i % 3)
        db.replace_daily(d, [(d, "spike", "KR", cnt, 0.0, "T"),
                             (d, "flat", "KR", 2, 0.0, "T")])
    bo = {x["id"]: x for x in H.detect_breakouts(db, asof_day=asof, recent_days=7,
                                                 baseline_days=90, z_min=2.0)}
    assert "spike" in bo and bo["spike"]["z"] >= 2.0
    assert "flat" not in bo                     # 변화 없는 키워드는 제외


def test_compute_rising_rollup_time_based(db):
    asof = H.today_utc()
    # 'rising': 베이스라인 낮다가 최근 급증 / 'steady': 계속 일정
    for i in range(21):
        d = H.day_add(asof, -i)
        rising_cnt = 12 if i < 3 else 1
        db.replace_daily(d, [(d, "rising", "KR", rising_cnt, 0.0, "T"),
                             (d, "steady", "KR", 5, 0.0, "T")])
    out = {x["id"]: x for x in H.compute_rising_rollup(db, recent_days=3, baseline_days=21)}
    assert "rising" in out and out["rising"]["growth"] > 0     # 시간 기준 상승 포착
    assert out["rising"]["prev"] < out["rising"]["recent"]
    assert "steady" not in out                                 # 변화 없으면 제외


def test_detect_seasonality_weekly(db):
    base = "2025-01-06"            # 월요일
    for w in range(40):
        for dow in range(7):
            d = H.day_add(base, w * 7 + dow)
            db.replace_daily(d, [(d, "weekly", "KR", 10 if dow == 0 else 1, 0.0, "T")])
    s = H.detect_seasonality(db, "weekly", days=300)
    wk = next(c for c in s["cycles"] if c["cycle"] == "weekly")
    assert wk["seasonal"] is True and wk["corr"] > 0.5
    assert s["seasonal"] is True
