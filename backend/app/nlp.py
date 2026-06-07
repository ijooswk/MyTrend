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
from .sentiment import score_text, label as sent_label

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
명 개 건 원 억 조 만 천 백 차 위 등 및 약 총 전 후 중 시 분 일 월 년 것 수 그 이 저 더 곳 점 측 셈 채 줄 데
공개 출시 확인 예상 전망 분석 보도 입장 영향 효과 모습 수준 규모 부분 측면 차원 가능성 중요성 관계 내용 의미 결과 과정 방법
무단 전재 배포 저작권 제공 사실 이유 목적 중심 대상 통한 따른 관한 위한 대비해 관련해 이라는 라는 한다는 위해서""".split())

STOP_EN = set("""the a an an and or but for nor on in at to of by with from into over after about as is are was were be been being
this that these those it its his her their our your my you we they he she them us new news say says said will would can could may
might more most than then so up out off down very just also amid how why what when who which has have had not no yes get got
year years day days time week month report reports update live video photo via amp top vs new latest first two one three
according including percent billion million company companies official officials told amid amids while still since back even
make made take takes set sets put puts way ways thing things lot use used using big small good best worse better""".split())

KO_PARTICLES = ["으로서", "으로써", "에서는", "에서도", "으로", "에서", "에게", "한테", "까지", "부터",
                "보다", "처럼", "이라", "라며", "라고", "이가", "은", "는", "이", "가", "을", "를",
                "에", "와", "과", "도", "만", "의", "로", "며", "란", "엔", "선"]

SHORT_KEEP = {"ai", "ev", "5g", "6g", "ml", "ar", "vr", "xr", "un", "eu", "us",
              "gpt", "llm", "iot", "gpu", "cpu", "ipo", "m&a", "ev"}

_HANGUL = re.compile(r"[가-힣]")
# 단어문자(영숫자·한글)와 &만 보존하고 나머지(공백·문장부호)는 모두 구분자로.
_SPLIT = re.compile(r"[^\w&]+", re.UNICODE)
_SRC_SUFFIX = re.compile(r"\s[-–—]\s[^-–—]+$")


def _strip_particle(tok: str) -> str:
    for p in KO_PARTICLES:
        if len(tok) > len(p) + 1 and tok.endswith(p):
            return tok[: len(tok) - len(p)]
    return tok


def _en_token(w: str, out: list[str]) -> None:
    wl = w.lower().replace("&", "")
    if not re.fullmatch(r"[a-z0-9]+", wl):
        return
    if wl in SHORT_KEEP:
        out.append(wl.upper())
    elif len(wl) >= 3 and wl not in STOP_EN and not wl.isdigit():
        out.append(wl)


def _kiwi_keywords(text: str) -> list[str]:
    """kiwi 형태소 분석 → 명사/외국어 키워드.

    인접한(공백 없는) 명사들을 복합명사로 결합해 함께 추출한다.
    예) '인공 지능 반도체' 류의 과분할을 보완하고, 개별 명사도 유지한다.
    """
    out: list[str] = []
    run: list[str] = []          # 현재 누적 중인 인접 명사들의 form
    prev_end = None
    def flush():
        if len(run) >= 2:
            comp = "".join(run)
            if 2 <= len(comp) <= 20 and comp not in STOP_KO:
                out.append(comp)
        run.clear()
    for tok in _kiwi().tokenize(text):
        form, tag = tok.form, tok.tag
        end = tok.start + tok.len
        if tag in ("NNG", "NNP"):
            if prev_end is not None and tok.start == prev_end and run:
                run.append(form)
            else:
                flush(); run.append(form)
            prev_end = end
            if len(form) >= 2 and form not in STOP_KO:
                out.append(form)
        else:
            flush(); prev_end = None
            if tag == "SL":               # 외국어(영문)
                fl = form.lower()
                if fl in SHORT_KEEP:
                    out.append(form.upper())
                elif len(form) >= 3 and fl not in STOP_EN:
                    out.append(fl)
    flush()
    return out


def tokenize(title: str) -> list[str]:
    """기사 제목 → 키워드 토큰 리스트(중복 포함)."""
    text = _SRC_SUFFIX.sub("", title or "").strip()
    out: list[str] = []

    kiwi = _kiwi()
    if kiwi and _HANGUL.search(text):
        try:
            out = _kiwi_keywords(text)
            for w in _SPLIT.split(text):  # 혼합 제목의 영문 보강
                _en_token(w, out)
            return out
        except Exception:
            out = []

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


def compute_rising(articles: list, mid_ts: float, *, top: int = 15,
                   min_recent: int = 2) -> list[dict]:
    """시간창을 둘로 나눠 최근 절반에서 급상승한 키워드를 산출.

    score = (recent - prev) / (prev + 1).  prev==0 이면 신규 급부상(isNew).
    """
    def g(a, k):
        return getattr(a, k) if not isinstance(a, dict) else a[k]

    recent: Counter = Counter()
    prev: Counter = Counter()
    catc: dict[str, Counter] = defaultdict(Counter)
    for a in articles:
        ts = g(a, "published_at")
        toks = set(tokenize(g(a, "title")))
        is_recent = ts >= mid_ts
        for w in toks:
            if is_recent:
                recent[w] += 1
                catc[w][g(a, "category")] += 1
            else:
                prev[w] += 1
    rising = []
    for w, rc in recent.items():
        if rc < min_recent:
            continue
        pc = prev.get(w, 0)
        if rc <= pc:
            continue
        rising.append({
            "id": w, "recent": rc, "prev": pc, "growth": rc - pc,
            "score": round((rc - pc) / (pc + 1), 2),
            "cat": catc[w].most_common(1)[0][0] if catc[w] else None,
            "isNew": pc == 0,
        })
    rising.sort(key=lambda x: (x["score"], x["growth"]), reverse=True)
    return rising[:top]


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
    kw_sent: dict[str, list] = defaultdict(list)        # 키워드별 감성 점수 모음
    cat_sent: dict[str, list] = defaultdict(list)       # 분야별 감성 점수 모음

    for a in articles:
        cat = g(a, "category")
        title = g(a, "title")
        s = score_text(title)
        cat_sent[cat].append(s)
        toks = list(dict.fromkeys(tokenize(title)))      # 기사 내 중복 제거
        for w in toks:
            freq[w] += 1
            cat_score[w][cat] += 1
            kw_sent[w].append(s)
            if len(kw_articles[w]) < 5:
                kw_articles[w].append({
                    "title": title, "url": g(a, "url"),
                    "publisher": g(a, "publisher"), "category": cat,
                })
        for x, y in combinations(sorted(toks), 2):
            co[(x, y)] += 1

    ranked = [w for w, c in freq.most_common() if c >= min_freq][:max_kw]
    keep = set(ranked)

    def avg(xs):
        return round(sum(xs) / len(xs), 3) if xs else 0.0

    nodes = []
    for w in ranked:
        cs = cat_score[w]
        top_cat = cs.most_common(1)[0][0]
        sent = avg(kw_sent[w])
        nodes.append({
            "id": w, "freq": freq[w], "cat": top_cat,
            "catScore": dict(cs), "articles": kw_articles[w],
            "sent": sent, "sentLabel": sent_label(sent),
        })

    links = []
    co_min = max(2, min_freq)
    for (x, y), c in co.items():
        if c >= co_min and x in keep and y in keep:
            links.append({"source": x, "target": y, "value": c})

    # 분야별 집계 (건수 + 평균 감성)
    by_cat = Counter(g(a, "category") for a in articles)
    cat_summary = [
        {"id": cid, "ko": CATEGORY_KO.get(cid, cid), "count": by_cat.get(cid, 0),
         "sentiment": avg(cat_sent.get(cid, []))}
        for cid in CATEGORY_KO
    ]
    overall = avg([s for xs in cat_sent.values() for s in xs])

    return {
        "kws": nodes,
        "links": links,
        "categorySummary": cat_summary,
        "articleCount": len(articles),
        "sentimentOverall": overall,
        "kiwi": _kiwi() is not None,
    }
