"""장기 누적 분석 레이어.

일별 키워드 롤업(daily_keyword)을 기반으로 수개월~수년 데이터에서 의미를 추출:
- 키워드 장기 시계열(일/주/월)
- 베이스라인 대비 돌발(breakout) 탐지(z-score)
- 계절성(주/월/년 주기) 자기상관 탐지
"""
from __future__ import annotations

import statistics as stat
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from .assoc import pearson
from .nlp import tokenize
from .sentiment import score_text

DAY = "%Y-%m-%d"


# ── 날짜 헬퍼 ──
def day_str(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime(DAY)


def _d(day: str) -> datetime:
    return datetime.strptime(day, DAY).replace(tzinfo=timezone.utc)


def day_bounds(day: str) -> tuple[float, float]:
    d = _d(day)
    return d.timestamp(), (d + timedelta(days=1)).timestamp()


def day_add(day: str, n: int) -> str:
    return (_d(day) + timedelta(days=n)).strftime(DAY)


def daterange(start: str, end: str) -> list[str]:
    a, b = _d(start), _d(end)
    out, cur = [], a
    while cur <= b:
        out.append(cur.strftime(DAY))
        cur += timedelta(days=1)
    return out


def today_utc() -> str:
    return datetime.now(timezone.utc).strftime(DAY)


# ── 롤업 ──
def rollup_day(db, day: str) -> int:
    """특정 날짜의 기사를 키워드×지역으로 집계해 daily_keyword 에 멱등 저장."""
    start, end = day_bounds(day)
    arts = db.query_between(start, end)
    agg: dict[tuple, list] = {}
    for a in arts:
        s = score_text(a.title)
        for w in set(tokenize(a.title)):
            k = (w, a.region)
            if k not in agg:
                agg[k] = [0, 0.0, Counter()]
            agg[k][0] += 1
            agg[k][1] += s
            agg[k][2][a.category] += 1
    rows = [(day, w, reg, c, ss, cat.most_common(1)[0][0])
            for (w, reg), (c, ss, cat) in agg.items()]
    return db.replace_daily(day, rows)


def backfill(db, *, max_days: int = 1200) -> dict:
    """저장된 기사 전 기간을 일별 롤업으로 백필."""
    lo, hi = db.article_time_bounds()
    if not lo:
        return {"days": 0, "rows": 0}
    days = daterange(day_str(lo), day_str(hi))[-max_days:]
    total = sum(rollup_day(db, d) for d in days)
    return {"days": len(days), "rows": total, "from": days[0], "to": days[-1]}


# ── 장기 시계열 ──
def _bucket(day: str, interval: str) -> str:
    if interval == "month":
        return day[:7]                       # YYYY-MM
    if interval == "week":
        d = _d(day)
        monday = d - timedelta(days=d.weekday())
        return monday.strftime(DAY)
    return day


def query_history(db, keyword: str, *, since_day: str, until_day: str,
                  interval: str = "day", regions=None) -> dict:
    series = db.daily_series(keyword, since_day=since_day, until_day=until_day, regions=regions)
    agg: dict[str, list] = defaultdict(lambda: [0, 0.0])   # period -> [count, sent_sum]
    for day, c, s in series:
        b = _bucket(day, interval)
        agg[b][0] += c
        agg[b][1] += s
    points = [{"period": p, "count": c, "sentiment": round(s / c, 3) if c else 0.0}
              for p, (c, s) in sorted(agg.items())]
    total = sum(p["count"] for p in points)
    return {"keyword": keyword, "interval": interval, "points": points, "total": total}


# ── 돌발 탐지(베이스라인 대비) ──
def detect_breakouts(db, *, asof_day: str | None = None, recent_days: int = 7,
                     baseline_days: int = 90, top: int = 20, min_recent: int = 3,
                     z_min: float = 2.0, regions=None) -> list[dict]:
    asof_day = asof_day or today_utc()
    since = day_add(asof_day, -(baseline_days - 1))
    rows = db.daily_all(since_day=since, until_day=asof_day, regions=regions)
    series: dict[str, dict] = defaultdict(dict)
    cat: dict[str, str] = {}
    for day, kw, c, s, ct in rows:
        series[kw][day] = c
        cat[kw] = ct
    recent_start = day_add(asof_day, -(recent_days - 1))
    base_days = daterange(since, day_add(recent_start, -1))
    rec_days = daterange(recent_start, asof_day)
    out = []
    for kw, dc in series.items():
        recent = sum(dc.get(d, 0) for d in rec_days)
        if recent < min_recent:
            continue
        base = [dc.get(d, 0) for d in base_days]
        mean = stat.mean(base) if base else 0.0
        std = stat.pstdev(base) if len(base) > 1 else 0.0
        rec_avg = recent / len(rec_days)
        if std > 0:
            z = (rec_avg - mean) / std
        else:
            z = 99.0 if rec_avg > mean else 0.0
        if z >= z_min:
            out.append({"id": kw, "recent": recent, "recent_avg": round(rec_avg, 2),
                        "baseline_avg": round(mean, 2), "z": round(z, 2), "cat": cat.get(kw)})
    out.sort(key=lambda x: x["z"], reverse=True)
    return out[:top]


# ── 계절성 탐지(자기상관) ──
_SEASON_LAGS = [("weekly", 7), ("monthly", 30), ("yearly", 365)]


def _autocorr(arr: list[float], lag: int) -> float:
    if len(arr) <= lag + 2:
        return 0.0
    return pearson(arr[:-lag], arr[lag:])


def detect_seasonality(db, keyword: str, *, days: int = 400, regions=None,
                       corr_min: float = 0.3) -> dict:
    until = today_utc()
    since = day_add(until, -(days - 1))
    series = dict((d, c) for d, c, _ in db.daily_series(
        keyword, since_day=since, until_day=until, regions=regions))
    arr = [series.get(d, 0) for d in daterange(since, until)]
    cycles = []
    for name, lag in _SEASON_LAGS:
        if len(arr) > lag * 2:
            r = _autocorr(arr, lag)
            cycles.append({"cycle": name, "lag": lag, "corr": round(r, 3),
                           "seasonal": r >= corr_min})
    return {"keyword": keyword, "span_days": len(arr), "cycles": cycles,
            "seasonal": any(c["seasonal"] for c in cycles)}
