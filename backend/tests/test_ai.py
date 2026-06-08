"""AI 레이어 테스트 — 실제 네트워크 호출 없이 chat 을 목(mock)으로 대체."""
import os
import time

os.environ.setdefault("MYTREND_INGEST_ON_START", "false")
os.environ.setdefault("MYTREND_INGEST_INTERVAL_MIN", "0")
os.environ["MYTREND_DB_PATH"] = ":memory:"

from app import ai
from app.db import Article


def _payload():
    return {
        "kws": [{"id": "AI", "freq": 5, "cat": "TECHNOLOGY", "sent": 0.3},
                {"id": "반도체", "freq": 4, "cat": "TECHNOLOGY", "sent": 0.2}],
        "rising": [{"id": "AI", "score": 4.0, "isNew": True}],
        "categorySummary": [{"id": "TECHNOLOGY", "ko": "테크", "count": 6, "sentiment": 0.25}],
        "clusters": [{"id": 0, "size": 3, "keywords": ["AI", "반도체", "엔비디아"], "cat": "TECHNOLOGY"}],
        "sentimentOverall": 0.25, "articleCount": 6,
    }


def test_prompt_builders_contain_data():
    msgs = ai.build_briefing_messages(_payload(), "ko")
    assert msgs[0]["role"] == "system" and "Korean" in msgs[0]["content"]
    assert "AI" in msgs[1]["content"] and "반도체" in msgs[1]["content"]
    lab = ai.build_label_messages(_payload()["clusters"], "en")
    assert "JSON" in lab[0]["content"] and "엔비디아" in lab[1]["content"]


def test_build_radar_messages():
    radar = [{"id": "AI", "volume": 5, "momentum": 0.7, "quadrant": "hot"},
             {"id": "에이전트", "volume": 2, "momentum": 0.6, "quadrant": "emerging"},
             {"id": "반도체", "volume": 6, "momentum": -0.1, "quadrant": "established"}]
    msgs = ai.build_radar_messages(radar, "ko")
    assert "Korean" in msgs[0]["content"] and "HOT" in msgs[1]["content"]
    assert "AI" in msgs[1]["content"]


def test_parse_labels_extracts_json():
    txt = 'Sure! [{"id":0,"label":"AI 반도체 경쟁"},{"id":1,"label":"금리"}] done'
    labels = ai.parse_labels(txt)
    assert labels == {0: "AI 반도체 경쟁", 1: "금리"}
    assert ai.parse_labels("no json here") == {}


def test_ai_routes_gated_when_disabled(monkeypatch):
    from fastapi.testclient import TestClient
    from app import main as m
    monkeypatch.setattr(ai, "ai_enabled", lambda: False)
    with TestClient(m.app) as c:
        assert c.get("/api/ai/status").json()["enabled"] is False
        assert c.post("/api/ai/briefing").status_code == 503
        assert c.post("/api/ai/ask", params={"q": "왜?"}).status_code == 503


def test_ai_models_endpoint(monkeypatch):
    from fastapi.testclient import TestClient
    from app import main as m

    async def fake_list():
        return [{"id": "openai/gpt-4o-mini", "label": "GPT-4o mini"},
                {"id": "anthropic/claude-3.5-sonnet", "label": "Claude Sonnet"}]
    monkeypatch.setattr(ai, "list_models", fake_list)
    with TestClient(m.app) as c:
        j = c.get("/api/ai/models").json()
        assert len(j["models"]) == 2 and "default" in j
        assert j["models"][0]["id"] == "openai/gpt-4o-mini"


def test_ai_model_param_passed_to_chat(monkeypatch):
    from fastapi.testclient import TestClient
    from app import main as m
    seen = {}

    async def fake_chat(messages, **kw):
        seen["model"] = kw.get("model")
        return "ok"
    monkeypatch.setattr(ai, "ai_enabled", lambda: True)
    monkeypatch.setattr(ai, "chat", fake_chat)
    with TestClient(m.app) as c:
        import time
        now = time.time()
        m.state["db"].upsert_many([Article(
            id="mp1", title="삼성전자 AI 반도체", url="u", source="rss", publisher="p",
            category="TECHNOLOGY", region="KR", lang="ko",
            published_at=now - 600, fetched_at=now)])
        c.post("/api/ai/briefing", params={"categories": ["TECHNOLOGY"], "regions": ["KR"],
                                           "model": "deepseek/deepseek-chat"})
        assert seen.get("model") == "deepseek/deepseek-chat"


def test_ai_briefing_with_mocked_chat(monkeypatch):
    from fastapi.testclient import TestClient
    from app import main as m

    async def fake_chat(messages, **kw):
        return "• 테크 분야가 가장 활발합니다.\n• AI가 급상승."

    monkeypatch.setattr(ai, "ai_enabled", lambda: True)
    monkeypatch.setattr(ai, "chat", fake_chat)
    with TestClient(m.app) as c:
        now = time.time()
        m.state["db"].upsert_many([Article(
            id=f"x{i}", title=t, url="u", source="rss", publisher="p",
            category="TECHNOLOGY", region="KR", lang="ko",
            published_at=now - 600, fetched_at=now)
            for i, t in enumerate(["삼성전자 AI 반도체 급등", "엔비디아 AI 반도체 수요"])])
        r = c.post("/api/ai/briefing", params={"lang": "ko", "categories": ["TECHNOLOGY"],
                                               "regions": ["KR"], "hours": 24})
        assert r.status_code == 200 and "AI" in r.json()["text"]
        # 두 번째 호출은 캐시 히트
        r2 = c.post("/api/ai/briefing", params={"lang": "ko", "categories": ["TECHNOLOGY"],
                                                "regions": ["KR"], "hours": 24})
        assert r2.json()["cached"] is True


def test_html_to_text_extracts_paragraphs():
    from app.extract import html_to_text
    html = ("<html><head><style>x{}</style></head><body><nav>menu</nav>"
            "<p>" + "삼성전자가 AI 반도체를 공개했다. " * 12 + "</p>"
            "<script>bad()</script><p>" + "수요가 급증하고 있다. " * 12 + "</p></body></html>")
    txt = html_to_text(html)
    assert "menu" not in txt and "bad()" not in txt
    assert "삼성전자" in txt and "수요" in txt


def test_build_keyword_digest_messages():
    docs = [{"title": "삼성 AI 칩 공개", "publisher": "BBC", "text": "본문 내용 전체..."}]
    msgs = ai.build_keyword_digest_messages("AI", docs, "ko")
    assert "Korean" in msgs[0]["content"] and "AI" in msgs[1]["content"]
    assert "본문 내용" in msgs[1]["content"]


def test_ai_keyword_digest_with_mocks(monkeypatch):
    from fastapi.testclient import TestClient
    from app import main as m, extract
    from app.db import Article
    import time

    async def fake_fetch_many(urls, **kw):
        return ["엔비디아와의 경쟁이 심화되고 있다. " * 20 for _ in urls]

    async def fake_chat(messages, **kw):
        return "• 핵심 요약: AI 반도체 경쟁 심화."

    monkeypatch.setattr(ai, "ai_enabled", lambda: True)
    monkeypatch.setattr(ai, "chat", fake_chat)
    monkeypatch.setattr(extract, "fetch_many", fake_fetch_many)
    with TestClient(m.app) as c:
        now = time.time()
        m.state["db"].upsert_many([Article(
            id="d1", title="삼성전자 AI 반도체 공개", url="http://x/1", source="rss",
            publisher="BBC", category="TECHNOLOGY", region="KR", lang="ko",
            published_at=now - 600, fetched_at=now)])
        r = c.post("/api/ai/keyword-digest", params={"keyword": "AI", "regions": ["KR"]})
        assert r.status_code == 200
        j = r.json()
        assert "AI" in j["summary"] and j["used"] >= 1 and len(j["articles"]) >= 1


def test_build_relate_messages():
    from app.db import Article
    arts = [Article(id="1", title="엔비디아 AI 반도체 수요 급증", url="u", source="s",
                    publisher="p", category="TECHNOLOGY", region="KR", lang="ko",
                    published_at=0, fetched_at=0)]
    msgs = ai.build_relate_messages("AI", "반도체", arts, "ko")
    assert "Keyword A: AI" in msgs[1]["content"] and "반도체" in msgs[1]["content"]
    assert "Korean" in msgs[0]["content"]


def test_ai_relate_with_mocked_chat(monkeypatch):
    from fastapi.testclient import TestClient
    from app import main as m

    async def fake_chat(messages, **kw):
        return "AI 수요가 반도체 수요를 견인합니다."

    monkeypatch.setattr(ai, "ai_enabled", lambda: True)
    monkeypatch.setattr(ai, "chat", fake_chat)
    with TestClient(m.app) as c:
        import time
        now = time.time()
        m.state["db"].upsert_many([Article(
            id="r1", title="엔비디아 AI 반도체 수요 급증", url="u", source="rss",
            publisher="p", category="TECHNOLOGY", region="KR", lang="ko",
            published_at=now - 600, fetched_at=now)])
        r = c.post("/api/ai/relate", params={"a": "AI", "b": "반도체", "regions": ["KR"]})
        assert r.status_code == 200 and "반도체" in r.json()["text"]


def test_ai_ask_with_mocked_chat(monkeypatch):
    from fastapi.testclient import TestClient
    from app import main as m

    async def fake_chat(messages, **kw):
        assert any("Question:" in mm["content"] for mm in messages)
        return "반도체 수요 급증이 원인입니다."

    monkeypatch.setattr(ai, "ai_enabled", lambda: True)
    monkeypatch.setattr(ai, "chat", fake_chat)
    with TestClient(m.app) as c:
        now = time.time()
        m.state["db"].upsert_many([Article(
            id="q1", title="엔비디아 AI 반도체 수요 급증", url="u", source="rss",
            publisher="p", category="TECHNOLOGY", region="KR", lang="ko",
            published_at=now - 600, fetched_at=now)])
        r = c.post("/api/ai/ask", params={"q": "왜 반도체가 올랐나?", "regions": ["KR"]})
        assert r.status_code == 200 and "반도체" in r.json()["answer"]
        assert r.json()["evidence"] >= 1
