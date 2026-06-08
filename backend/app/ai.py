"""OpenRouter 기반 AI 레이어: 브리핑·토픽 라벨링·Q&A.

모든 호출은 사용자가 명시적으로 트리거하는 온디맨드 방식이며, 동일 입력은 캐시한다.
키가 없으면 AIUnavailable 을 던지고 라우트가 503 으로 안내한다.
"""
from __future__ import annotations

import hashlib
import json
import time
from collections import Counter, defaultdict

import httpx

from .config import CATEGORY_KO, get_settings

ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"


class AIUnavailable(Exception):
    """AI 비활성(키 미설정) 또는 일시 오류."""


def ai_enabled() -> bool:
    return bool(get_settings().openrouter_api_key)


# ── 간단 TTL 캐시 ──
_CACHE: dict[str, tuple[float, str]] = {}


def _ck(*parts) -> str:
    return hashlib.sha1(json.dumps(parts, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _cache_get(k: str):
    hit = _CACHE.get(k)
    if hit and hit[0] > time.time():
        return hit[1]
    return None


def _cache_put(k: str, v: str):
    if len(_CACHE) > 256:
        _CACHE.clear()
    _CACHE[k] = (time.time() + get_settings().mytrend_ai_cache_ttl, v)


async def chat(messages: list[dict], *, max_tokens: int | None = None,
               temperature: float = 0.4, model: str | None = None) -> str:
    """OpenRouter chat completion. 키 없으면 AIUnavailable."""
    s = get_settings()
    if not s.openrouter_api_key:
        raise AIUnavailable("OpenRouter API key not set")
    payload = {
        "model": model or s.mytrend_ai_model,
        "messages": messages,
        "max_tokens": max_tokens or s.mytrend_ai_max_tokens,
        "temperature": temperature,
    }
    headers = {
        "Authorization": f"Bearer {s.openrouter_api_key}",
        "Content-Type": "application/json",
        "X-Title": "MyTrend",
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
            r = await client.post(ENDPOINT, headers=headers, json=payload)
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPError as e:
        raise AIUnavailable(f"OpenRouter request failed: {e}") from e
    return data["choices"][0]["message"]["content"].strip()


# ───────────────────────── 프롬프트 빌더 ─────────────────────────
def _lang_name(lang: str) -> str:
    return "Korean" if lang == "ko" else "English"


def _trend_digest(payload: dict, *, max_kw: int = 25) -> str:
    """트렌드 페이로드를 LLM 입력용 간결 텍스트로 압축."""
    kws = payload.get("kws", [])[:max_kw]
    lines = ["TOP KEYWORDS (keyword | freq | field | sentiment):"]
    for k in kws:
        lines.append(f"- {k['id']} | {k['freq']} | {CATEGORY_KO.get(k['cat'], k['cat'])} | {k.get('sent', 0)}")
    rising = payload.get("rising", [])[:8]
    if rising:
        lines.append("RISING: " + ", ".join(f"{r['id']}(x{r['score']}{',NEW' if r.get('isNew') else ''})" for r in rising))
    cats = [c for c in payload.get("categorySummary", []) if c.get("count")]
    if cats:
        lines.append("BY FIELD: " + ", ".join(f"{c['ko']}={c['count']}(sent {c.get('sentiment', 0)})" for c in cats))
    cl = payload.get("clusters", [])[:6]
    if cl:
        lines.append("TOPIC CLUSTERS: " + " | ".join("·".join(c["keywords"][:5]) for c in cl))
    lines.append(f"OVERALL SENTIMENT: {payload.get('sentimentOverall', 0)}  ARTICLES: {payload.get('articleCount', 0)}")
    return "\n".join(lines)


def build_briefing_messages(payload: dict, lang: str) -> list[dict]:
    lname = _lang_name(lang)
    system = (f"You are a sharp news-trend analyst. Using ONLY the structured trend data, "
              f"write a concise briefing in {lname}. Be factual and specific, no speculation or fabricated facts. "
              f"Format: one headline sentence, then 3-5 short bullet points (•) covering the dominant theme, "
              f"notable rising keywords, sentiment, and any cross-field signal. Keep it tight.")
    user = "Trend data:\n" + _trend_digest(payload)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def build_label_messages(clusters: list[dict], lang: str) -> list[dict]:
    lname = _lang_name(lang)
    system = (f"You label topic clusters. For each cluster of news keywords, produce a short 2-5 word "
              f"theme label in {lname}. Respond ONLY with a strict JSON array of objects "
              f'{{"id": <int>, "label": <string>}} and nothing else.')
    items = [{"id": c["id"], "keywords": c["keywords"]} for c in clusters]
    user = "Clusters:\n" + json.dumps(items, ensure_ascii=False)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def build_qa_messages(question: str, articles: list, lang: str, *, limit: int = 60) -> list[dict]:
    lname = _lang_name(lang)
    def g(a, k):
        return getattr(a, k) if not isinstance(a, dict) else a[k]
    heads = []
    for i, a in enumerate(articles[:limit], 1):
        heads.append(f"{i}. {g(a, 'title')} [{CATEGORY_KO.get(g(a, 'category'), g(a, 'category'))}]")
    system = (f"You answer questions about current news using ONLY the provided headlines as evidence. "
              f"If the headlines do not contain enough information, say so honestly. "
              f"Answer in {lname}, concise (2-4 sentences). Do not invent facts or sources.")
    user = f"Headlines:\n" + "\n".join(heads) + f"\n\nQuestion: {question}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def build_radar_messages(radar: list[dict], lang: str) -> list[dict]:
    lname = _lang_name(lang)
    groups: dict[str, list] = defaultdict(list)
    for r in sorted(radar, key=lambda x: -x["volume"]):
        groups[r["quadrant"]].append(f"{r['id']}(vol {r['volume']}, mom {r['momentum']:+})")
    order = ["hot", "emerging", "established", "fading"]
    lines = [f"{q.upper()}: " + ", ".join(groups[q][:10]) for q in order if groups.get(q)]
    system = (f"You are a strategic news-trend analyst reading a momentum×volume radar. "
              f"Quadrants: HOT(high volume & rising), EMERGING(low volume & rising), "
              f"ESTABLISHED(high volume & stable/declining), FADING(low volume & declining). "
              f"Write a concise strategic reading in {lname}: 4-6 short bullets (•) — what is breaking out, "
              f"what to watch early (emerging), what is cooling, plus one actionable takeaway. "
              f"Factual, grounded in the data, no fabrication.")
    user = "Radar quadrants:\n" + "\n".join(lines)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def build_keyword_digest_messages(keyword: str, docs: list[dict], lang: str) -> list[dict]:
    """관련 기사 본문(docs: {title, publisher, text})으로 키워드 심층 분석 프롬프트."""
    lname = _lang_name(lang)
    blocks = []
    for i, d in enumerate(docs, 1):
        body = (d.get("text") or d.get("summary") or "").strip()
        blocks.append(f"[기사 {i}] {d.get('title','')} ({d.get('publisher','')})\n{body}")
    system = (f"You are a news analyst. Using ONLY the FULL article texts below about the keyword "
              f"'{keyword}', write a structured analysis in {lname} with these sections:\n"
              f"• 핵심 요약 (3-4 sentences)\n• 주요 사실/쟁점 (bullet points)\n• 시사점/맥락 (2-3 sentences)\n"
              f"Ground every statement in the provided texts. Do not invent facts, numbers, or quotes. "
              f"If the texts are thin, say so honestly.")
    user = f"키워드: {keyword}\n\n" + "\n\n---\n\n".join(blocks)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def build_relate_messages(a: str, b: str, articles: list, lang: str, *, limit: int = 40) -> list[dict]:
    lname = _lang_name(lang)
    def g(x, k):
        return getattr(x, k) if not isinstance(x, dict) else x[k]
    heads = [f"- {g(x, 'title')}" for x in articles[:limit]]
    system = (f"You explain how two news keywords are related, using ONLY the provided headlines. "
              f"Answer in {lname}, 2-3 sentences. If the headlines don't show a real connection, "
              f"say they appear unrelated. No fabrication.")
    user = f"Keyword A: {a}\nKeyword B: {b}\nHeadlines:\n" + "\n".join(heads)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def parse_labels(text: str) -> dict[int, str]:
    """LLM 응답에서 JSON 배열을 추출해 {cluster_id: label} 로 변환."""
    s = text.strip()
    a, b = s.find("["), s.rfind("]")
    if a == -1 or b == -1:
        return {}
    try:
        arr = json.loads(s[a:b + 1])
    except Exception:
        return {}
    out = {}
    for it in arr:
        try:
            out[int(it["id"])] = str(it["label"]).strip()
        except Exception:
            continue
    return out


# 캐시 헬퍼를 외부에서 사용
def cache_get(*parts):
    return _cache_get(_ck(*parts))


def cache_put(value: str, *parts):
    _cache_put(_ck(*parts), value)
    return value
