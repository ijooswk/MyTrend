"""연관도(NPMI)·시계열 상관 엔진 테스트."""
import time

from app.assoc import (compute_associations, npmi, pearson,
                       temporal_edges, correlation_matrix)
from app.db import Article


def _arts(titles):
    now = time.time()
    return [Article(id=str(i), title=t, url="u", source="s", publisher="p",
                    category="X", region="KR", lang="ko",
                    published_at=now, fetched_at=now, summary="")
            for i, t in enumerate(titles)]


def test_npmi_bounds_and_independence():
    # 항상 함께(2/2) → NPMI=1
    assert abs(npmi(2, 2, 2, 2) - 1.0) < 1e-9
    # 독립: p_ab == p_a*p_b → NPMI≈0
    assert abs(npmi(100, 10, 10, 1)) < 1e-9
    # 함께 한 번도 안 나옴
    assert npmi(10, 5, 5, 0) == 0.0


def test_associations_separate_topics():
    arts = _arts(["삼성전자 AI 반도체 급등", "엔비디아 AI 반도체 수요",
                  "AI 반도체 엔비디아 신제품", "기준금리 물가 한국은행 동결",
                  "한국은행 금리 물가 인상", "금리 물가 우려 한국은행"])
    keep = ["AI", "반도체", "엔비디아", "금리", "물가", "한국은행"]
    edges = compute_associations(arts, keep, min_co=2, min_npmi=0.1)
    pairs = {tuple(sorted((e["source"], e["target"]))) for e in edges}
    assert ("AI", "반도체") in pairs
    assert ("금리", "물가") in pairs
    # 서로 다른 토픽은 연결되지 않아야 함(상관 품질의 핵심)
    assert ("AI", "금리") not in pairs
    assert all(-1.0 <= e["npmi"] <= 1.0 for e in edges)


def test_pearson_and_temporal_edges():
    assert pearson([1, 2, 3, 4], [2, 4, 6, 8]) > 0.99       # 완전 양의 상관
    assert pearson([1, 2, 3, 4], [4, 3, 2, 1]) < -0.99      # 완전 음의 상관
    series = {"a": [0, 1, 2, 3, 4], "b": [0, 1, 2, 3, 4], "c": [4, 3, 2, 1, 0]}
    edges = temporal_edges(series, min_corr=0.6, min_activity=3)
    pairs = {tuple(sorted((e["source"], e["target"]))) for e in edges}
    assert ("a", "b") in pairs          # 동조
    assert ("a", "c") not in pairs      # 반대로 움직임


def test_correlation_matrix_shape():
    series = {"a": [1, 2, 3], "b": [1, 2, 3]}
    m = correlation_matrix(series, ["a", "b"])
    assert len(m) == 2 and len(m[0]) == 2
    assert m[0][0] == 1.0 and m[1][1] == 1.0
