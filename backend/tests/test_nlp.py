"""키워드 추출·복합명사·감성 단위테스트."""
import time

from app.nlp import tokenize, build_trends, compute_rising, compute_radar
from app.sentiment import score_text, label


def test_english_lowercase_preserved():
    # _SPLIT 정규식 회귀 테스트: 소문자가 삼켜지면 안 됨
    toks = tokenize("OpenAI releases new GPT model, raising AI competition - The Verge")
    assert "openai" in toks
    assert "competition" in toks
    assert "AI" in toks and "GPT" in toks   # 약어는 대문자 보존


def test_short_acronym_kept_and_stopwords_dropped():
    toks = tokenize("The new big AI deal is here")
    assert "AI" in toks
    assert "the" not in toks and "new" not in toks and "big" not in toks


def test_generic_low_information_words_filtered():
    # 특정 의미가 약한 generic 단어는 키워드에서 제외(한/영)
    toks = tokenize("정부 대응 가능성, 위기 시장 상황 주목 — 점검 필요")
    for w in ["대응", "가능성", "위기", "시장", "상황", "주목", "점검", "정부"]:
        assert w not in toks
    en = tokenize("Market crisis: demand and support measures, possible response")
    for w in ["market", "crisis", "demand", "support", "measures", "possible", "response"]:
        assert w not in en
    # 의미있는 키워드는 보존
    keep = tokenize("삼성전자 AI 반도체 위기 대응 시장")
    assert "삼성전자" in keep and "AI" in keep and "반도체" in keep


def test_korean_compound_noun_merge():
    # kiwi가 '인공지능'을 인공/지능으로 과분할하면 인접(공백 없음) 결합으로 복원
    toks = tokenize("삼성전자 인공지능 반도체 신제품 공개")
    assert "인공지능" in toks
    assert "반도체" in toks
    assert "공개" not in toks            # 불용어 제거


def test_sentiment_polarity():
    assert score_text("주가 급등 호황 신기록") > 0
    assert score_text("위기 적자 손실 우려") < 0
    assert score_text("Stocks surge to record growth") > 0
    assert score_text("Markets plunge amid recession fears") < 0
    assert score_text("그냥 평범한 발표") == 0.0
    assert label(0.5) == "pos" and label(-0.5) == "neg" and label(0.0) == "neu"


def _arts(rows, ts=None):
    from app.db import Article
    ts = ts or time.time()
    return [Article(id=f"{i}", title=t, url="u", source="s", publisher="p",
                    category=c, region="KR", lang="ko", published_at=ts, fetched_at=ts)
            for i, (t, c) in enumerate(rows)]


def test_build_trends_structure_and_sentiment():
    arts = _arts([("삼성전자 AI 반도체 급등", "TECHNOLOGY"),
                  ("엔비디아 AI 반도체 수요", "TECHNOLOGY"),
                  ("기준금리 동결 물가 우려", "BUSINESS")])
    tr = build_trends(arts, min_freq=1, max_kw=50)
    ids = {k["id"] for k in tr["kws"]}
    assert "AI" in ids and "반도체" in ids
    # 동시출현 링크: AI-반도체
    pairs = {tuple(sorted((l["source"], l["target"]))) for l in tr["links"]}
    assert ("AI", "반도체") in pairs
    # 감성 필드 존재
    assert all("sent" in k and "sentLabel" in k for k in tr["kws"])
    assert "sentimentOverall" in tr
    cats = {c["id"]: c for c in tr["categorySummary"]}
    assert cats["TECHNOLOGY"]["count"] == 2
    assert "sentiment" in cats["BUSINESS"]


def test_radar_quadrant_classification():
    import time
    now = time.time()
    mid = now - 6 * 3600

    def mk(t, ts):
        from app.db import Article
        return Article(id=t + str(ts), title=t, url="u", source="s", publisher="p",
                       category="T", region="KR", lang="ko",
                       published_at=ts, fetched_at=now, summary="")
    arts = [mk("반도체 업황", mid - 3600) for _ in range(5)]          # 과거 다수
    arts += [mk("AI 에이전트 신규 부상", mid + 1800) for _ in range(3)]  # 최근 신규
    tr = build_trends(arts, min_freq=1, max_kw=30, assoc_threshold=0.1)
    radar = {r["id"]: r for r in compute_radar(arts, tr["kws"], tr["links"], mid)}
    assert radar["AI"]["momentum"] > 0 and radar["AI"]["quadrant"] in ("hot", "emerging")
    assert radar["반도체"]["momentum"] < 0          # 최근 등장 감소 → 하락
    assert all(q["quadrant"] in ("hot", "emerging", "established", "fading")
               for q in radar.values())


def test_topic_clustering_separates_themes():
    arts = _arts([("삼성전자 AI 반도체", "TECHNOLOGY"),
                  ("엔비디아 AI 반도체 수요", "TECHNOLOGY"),
                  ("AI 반도체 엔비디아 공급", "TECHNOLOGY"),
                  ("기준금리 물가 한국은행", "BUSINESS"),
                  ("한국은행 금리 물가 동결", "BUSINESS"),
                  ("금리 물가 인상 우려", "BUSINESS")])
    tr = build_trends(arts, min_freq=1, max_kw=40)
    assert len(tr["clusters"]) >= 2
    cl_of = {k["id"]: k["cluster"] for k in tr["kws"]}
    # 같은 토픽은 같은 군집, 다른 토픽은 다른 군집
    assert cl_of["AI"] == cl_of["반도체"]
    assert cl_of["금리"] == cl_of["물가"]
    assert cl_of["AI"] != cl_of["금리"]


def test_compute_rising_detects_new_keyword():
    now = time.time()
    mid = now - 6 * 3600
    arts = _arts([("반도체 업황", "TECHNOLOGY")] * 3, ts=mid - 3600)        # 이전 절반
    arts += _arts([("AI 에이전트 확산", "TECHNOLOGY")] * 5, ts=mid + 3600)  # 최근 절반(신규)
    rising = compute_rising(arts, mid, top=10, min_recent=2)
    rids = {r["id"] for r in rising}
    assert "AI" in rids
    ai = next(r for r in rising if r["id"] == "AI")
    assert ai["isNew"] is True and ai["prev"] == 0
    assert "반도체" not in rids            # 하락/유지 키워드는 제외
