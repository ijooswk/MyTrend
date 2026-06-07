"""경량 감성 분석 (한/영 극성 사전 기반).

뉴스 제목의 긍/부정 신호어를 세어 -1.0~+1.0 점수를 산출한다.
외부 모델 없이 동작하며, EODHD 등에서 제공하는 점수가 있으면 그대로 사용할 수 있다.
"""
from __future__ import annotations

import re

POS_EN = set("""surge surges surged soar soars gain gains rise rises rising jump jumps boost boosts record growth
profit profits beat beats win wins won success breakthrough upgrade upgraded rally rallies strong optimism recovery
recover expand approval approve approved agreement deal support positive outperform milestone leads leading rebound""".split())
NEG_EN = set("""fall falls fell drop drops plunge plunges crash loss losses decline declines slump fear fears risk crisis
war conflict death dead killed layoff layoffs cut cuts recession lawsuit fraud scandal ban banned warning threat weak
slowdown default collapse negative attack protest sanction sanctions downgrade slump struggle struggles miss misses""".split())

POS_KO = ["상승", "급등", "호황", "성장", "흑자", "최고", "신기록", "돌파", "호조", "개선", "회복", "타결",
          "합의", "성공", "수혜", "기대", "호재", "강세", "반등", "승리", "혁신", "수출", "흥행", "낙관", "도약"]
NEG_KO = ["하락", "급락", "폭락", "추락", "위기", "적자", "손실", "감소", "부진", "우려", "공포", "위험",
          "전쟁", "분쟁", "사망", "사고", "해고", "감원", "파산", "소송", "사기", "논란", "의혹", "비판",
          "제재", "경고", "위협", "약세", "침체", "붕괴", "충돌", "시위", "규제", "갈등", "피해", "악재", "쇼크"]

_WORD = re.compile(r"[a-zA-Z]+")


def score_text(text: str) -> float:
    """제목 → 감성 점수(-1.0 매우 부정 ~ +1.0 매우 긍정). 신호 없으면 0.0."""
    if not text:
        return 0.0
    pos = neg = 0
    for w in _WORD.findall(text.lower()):
        if w in POS_EN:
            pos += 1
        elif w in NEG_EN:
            neg += 1
    for w in POS_KO:
        if w in text:
            pos += 1
    for w in NEG_KO:
        if w in text:
            neg += 1
    if pos + neg == 0:
        return 0.0
    return round((pos - neg) / (pos + neg), 3)


def label(score: float) -> str:
    if score >= 0.2:
        return "pos"
    if score <= -0.2:
        return "neg"
    return "neu"
