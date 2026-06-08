"""키워드 연관도 엔진.

- NPMI(정규화 점별상호정보): 한계빈도를 보정해 '의미있게 함께 등장'하는 쌍을 부각.
- 백본 필터: 노드별 상위 k개 엣지만 남겨 헤어볼 제거.
- 시계열 동조 상관: 함께 뜨고 함께 지는 키워드(피어슨 상관).
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from itertools import combinations

from .nlp import tokenize


def _doc_tokens(article, keepset: set) -> set:
    """기사 제목+요약에서 keep 집합에 속하는 토큰만 추출(동시출현 신호 강화)."""
    def g(a, k):
        return getattr(a, k, "") if not isinstance(a, dict) else a.get(k, "")
    toks = {w for w in tokenize(g(article, "title")) if w in keepset}
    summ = g(article, "summary")
    if summ:
        toks |= {w for w in tokenize(summ[:300]) if w in keepset}
    return toks


def cooccur_stats(articles: list, keep: list[str]):
    """(N, freq, co) — 제목+요약 기준 문서빈도와 동시출현."""
    keepset = set(keep)
    freq: Counter = Counter()
    co: Counter = Counter()
    N = 0
    for a in articles:
        toks = _doc_tokens(a, keepset)
        N += 1
        for w in toks:
            freq[w] += 1
        for x, y in combinations(sorted(toks), 2):
            co[(x, y)] += 1
    return N, freq, co


def npmi(n: int, fa: int, fb: int, fab: int) -> float:
    """NPMI ∈ [-1,1].  1=항상 함께, 0=독립, -1=배타."""
    if n <= 0 or fab <= 0 or fa <= 0 or fb <= 0:
        return 0.0
    p_ab = fab / n
    p_a = fa / n
    p_b = fb / n
    pmi = math.log(p_ab / (p_a * p_b))
    denom = -math.log(p_ab)
    if denom == 0:
        return 0.0
    return max(-1.0, min(1.0, pmi / denom))


def compute_associations(articles: list, keep: list[str], *, min_co: int = 2,
                         min_npmi: float = 0.2, top_per_node: int = 6) -> list[dict]:
    """NPMI 기반 연관 엣지(백본 필터 적용)를 반환.

    각 엣지: {source, target, count, npmi, value}.  value=count(프론트 호환).
    """
    N, freq, co = cooccur_stats(articles, keep)
    candidates = []
    for (x, y), c in co.items():
        if c < min_co:
            continue
        score = npmi(N, freq[x], freq[y], c)
        if score >= min_npmi:
            candidates.append({"source": x, "target": y, "count": c,
                               "npmi": round(score, 3), "value": c})
    # 백본: 노드별 NPMI 상위 top_per_node 만 유지(합집합)
    by_node: dict[str, list] = defaultdict(list)
    for e in candidates:
        by_node[e["source"]].append(e)
        by_node[e["target"]].append(e)
    keep_ids = set()
    for node, edges in by_node.items():
        edges.sort(key=lambda e: e["npmi"], reverse=True)
        for e in edges[:top_per_node]:
            keep_ids.add((e["source"], e["target"]))
    return [e for e in candidates if (e["source"], e["target"]) in keep_ids]


# ───────────────────────── 시계열 동조 상관 ─────────────────────────
def pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 3:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return 0.0
    return max(-1.0, min(1.0, num / (dx * dy)))


def temporal_edges(series: dict[str, list[int]], *, min_corr: float = 0.5,
                   min_activity: int = 3, top_per_node: int = 6) -> list[dict]:
    """키워드 시계열 간 피어슨 상관이 높은(동조하는) 쌍을 엣지로."""
    keys = [k for k, v in series.items() if sum(v) >= min_activity]
    edges = []
    for x, y in combinations(sorted(keys), 2):
        r = pearson(series[x], series[y])
        if r >= min_corr:
            edges.append({"source": x, "target": y, "corr": round(r, 3),
                          "value": round(r * 5, 2), "npmi": round(r, 3)})
    by_node: dict[str, list] = defaultdict(list)
    for e in edges:
        by_node[e["source"]].append(e)
        by_node[e["target"]].append(e)
    keep_ids = set()
    for node, es in by_node.items():
        es.sort(key=lambda e: e["corr"], reverse=True)
        for e in es[:top_per_node]:
            keep_ids.add((e["source"], e["target"]))
    return [e for e in edges if (e["source"], e["target"]) in keep_ids]


def correlation_matrix(series: dict[str, list[int]], keywords: list[str]) -> list[list[float]]:
    """keywords 순서대로 NxN 피어슨 상관 행렬."""
    return [[1.0 if a == b else round(pearson(series.get(a, []), series.get(b, [])), 3)
             for b in keywords] for a in keywords]
