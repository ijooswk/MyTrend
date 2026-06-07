"""키워드 추출 + 트렌드(빈도·동시출현·분야연관) 분석 엔진.

한국어: kiwipiepy 형태소 분석으로 명사 추출(설치 시). 미설치면 휴리스틱 폴백.
영어: 불용어 제거 토크나이저 + 주요 약어 보존.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from itertools import combinations
from typing import Iterable

from .config import CATEGORY_KO

# ── kiwipiepy 선택 로딩 ──
_KIWI = None
_KIWI_TRIED = False


def _kiwi():
    global _KIWI, _KIWI_TRIED
    if not _KIWI_TRIED:
        _KIWI_TRIED = True
        try:
            from kiwipiepy import Kiwi
            _KIWI = Kiwi()
        except Exception:
            _KIWI = None
    return _KIWI


STOP_KO = set("""그리고 그러나 하지만 또한 또는 위해 통해 대해 관련 대한 가운데 이번 지난 오늘 내일 어제 올해 작년 내년
모든 각종 일부 관계자 기자 뉴스 사진 영상 속보 단독 종합 정부 한국 우리 이날 당시 이후 이전 최근 현재 만큼 동안 가장 매우 다시
오전 오후 기준 대비 경우 정도 예정 계획 추진 발표 진행 확대 강화 마련 방안 상황 문제 필요 사람 우리 자신 때문 이상 이하
명 개 건 원 억 조 만 천 백 차 위 등 및 약 총 전 후 중 시 분 일 월 년 것 수 그 이 저 더 곳 점 측 셈 채 줄 데""".split())

STOP_EN = set("""the a an and or but for nor on in at to of by with from into over after about as is are was were be been being
this that these those it its his her their our your my you we they he she them us new news say says said will would can could may
might more most than then so up out off down very just also amid how why what when who which has have had not no yes get got
year years day days time week month report reports update live video photo via amp top vs new latest first two one three""".split())

KO_PARTICLES = ["으로서", "으로써", "에서는", "에서도", "으로", "에서", "에게", "한테", "까지", "부터",
                "보다", "처럼", "이라", "라며", "라고", "이가", "은", "는", "이", "가", "을", "를",
                "에", "와", "과", "도", "만", "의", "로", "며", "란", "엔", "선"]

SHORT_KEEP = {"ai", "ev", "5g", "6g", "ml", "ar", "vr", "xr", "un", "eu", "us",
              "gpt", "llm", "iot", "gpu", "cpu", "ipo", "m&a", "ev"}

_HANGUL = re.compile(r"[가-힣]")
_SPLIT = re.compile(r"[\s,./()\[\]{}\"'""''·…|!?:;~`@#$%^&*+=<>\\\-–—]+")
_SRC_SUFFIX = re.compile(r"\s[-–—]\s[^-–—]+$")


def _strip_particle(tok: str) -> str:
    for p in KO_PARTICLES:
        if len(tok) > len(p) + 1 and tok.endswith(p):
            return tok[: len(tok) - len(p)]
    return tok


def tokenize(title: str) -> list[str]:
    """기사 제목 → 키워드 토큰 리스트(중복 포함)."""
    text = _SRC_SUFFIX.sub("", title or "").strip()
    out: list[str] = []

    kiwi = _kiwi()
    if kiwi and _HANGUL.search(text):
        # 한국어 구간은 형태소 분석으로 명사(NNG/NNP) 추출
        try:
            for tok in kiwi.tokenize(text):
                form, tag = tok.form, tok.tag
                if tag in ("NNG", "NNP", "SL") and len(form) >= 2 and form not in STOP_KO:
                    out.append(form)
                elif tag == "SL" and form.lower() in SHORT_KEEP:
                    out.append(form.upper())
            # 영문 토큰도 별도 처리(혼합 제목 대비)
            for w in _SPLIT.split(text):
                wl = w.lower().replace("&", "")
                if re.fullmatch(r"[a-z0-9]+", wl):
                    if wl in SHORT_KEEP:
                        out.append(wl.upper())
                    elif len(wl) >= 3 and wl not in STOP_EN and not wl.isdigit():
                        out.append(wl)
            return list(dict.fromkeys(out)) if False else out
        except Exception:
            pass

    # 휴리스틱 폴백
    for w in _SPLIT.split(text):
        if not w:
            continue
        if _HANGUL.search(w):
            w2 = _strip_particle(re.sub(r"[^가-힣A-Za-z0-9]", "", w))
            if len(w2) >= 2 and w2 not in STOP_KO:
                out.append(w2)
        else:
            wl = re.sub(r"[^a-z0-9&]", "", w.lower())
            if wl in SHORT_KEEP:
                out.append(wl.upper())
            elif len(wl) >= 3 and wl not in STOP_EN and not wl.isdigit():
                out.append(wl)
    return out


def build_trends(articles: list, *, min_freq: int = 2, max_kw: int = 80) -> dict:
    """기사 리스트 → 트렌드 맵 JSON(nodes/links + 분야 집계).

    articles: dataclass Article 또는 dict 모두 허용.
    """
    def g(a, k):
        return getattr(a, k) if not isinstance(a, dict) else a[k]

    freq: Counter = Counter()
    cat_score: dict[str, Counter] = defaultdict(Counter)
    co: Counter = Counter()
    kw_articles: dict[str, list] = defaultdict(list)

    for a in articles:
        cat = g(a, "category")
        toks = list(dict.fromkeys(tokenize(g(a, "title"))))  # 기사 내 중복 제거
        for w in toks:
            freq[w] += 1
            cat_score[w][cat] += 1
            if len(kw_articles[w]) < 5:
                kw_articles[w].append({
                    "title": g(a, "title"), "url": g(a, "url"),
                    "publisher": g(a, "publisher"), "category": cat,
                })
        for x, y in combinations(sorted(toks), 2):
            co[(x, y)] += 1

    ranked = [w for w, c in freq.most_common() if c >= min_freq][:max_kw]
    keep = set(ranked)

    nodes = []
    for w in ranked:
        cs = cat_score[w]
        top_cat = cs.most_common(1)[0][0]
        nodes.append({
            "id": w, "freq": freq[w], "cat": top_cat,
            "catScore": dict(cs), "articles": kw_articles[w],
        })

    links = []
    co_min = max(2, min_freq)
    for (x, y), c in co.items():
        if c >= co_min and x in keep and y in keep:
            links.append({"source": x, "target": y, "value": c})

    # 분야별 집계
    by_cat = Counter(g(a, "category") for a in articles)
    cat_summary = [
        {"id": cid, "ko": CATEGORY_KO.get(cid, cid), "count": by_cat.get(cid, 0)}
        for cid in CATEGORY_KO
    ]

    return {
        "kws": nodes,
        "links": links,
        "categorySummary": cat_summary,
        "articleCount": len(articles),
        "kiwi": _kiwi() is not None,
    }
