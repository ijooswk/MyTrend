"""설정·분야·지역·소스 메타데이터 정의."""
from __future__ import annotations

from functools import lru_cache
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore",
                                      case_sensitive=False)

    # API 키 (없으면 해당 소스 비활성)
    tavily_api_key: str = ""
    # EODHD 는 EODHD_API_KEY 또는 EODHD_API_TOKEN 둘 다 허용
    eodhd_api_key: str = Field(
        "", validation_alias=AliasChoices("EODHD_API_KEY", "EODHD_API_TOKEN"))
    newsapi_key: str = ""
    # OpenRouter (LLM 게이트웨이) — 트렌드 요약 등 LLM 기능용
    openrouter_api_key: str = ""

    # 동작 설정
    mytrend_db_path: str = "mytrend.db"
    mytrend_ingest_interval_min: int = 20
    mytrend_default_hours: int = 24
    mytrend_per_feed_limit: int = 60
    mytrend_cache_ttl: int = 120
    mytrend_ingest_on_start: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()


# ── 분야 (canonical category) ──
# id: 내부코드, ko: 한글, color: 프론트 색, queries: 검색형 소스용 질의(ko/en)
CATEGORIES = [
    {"id": "BUSINESS",   "ko": "경제", "color": "#34d399",
     "q_ko": "경제 OR 금융 OR 증시 OR 산업 OR 부동산",
     "q_en": "economy OR finance OR markets OR business"},
    {"id": "NATION",     "ko": "사회", "color": "#f59e0b",
     "q_ko": "사회 OR 사건 OR 사고 OR 정책 OR 노동",
     "q_en": "society OR crime OR policy OR labor"},
    {"id": "SCIENCE",    "ko": "과학", "color": "#a78bfa",
     "q_ko": "과학 OR 연구 OR 우주 OR 기후 OR 생명",
     "q_en": "science OR research OR space OR climate"},
    {"id": "TECHNOLOGY", "ko": "테크", "color": "#38bdf8",
     "q_ko": "기술 OR IT OR 인공지능 OR 반도체 OR 스타트업",
     "q_en": "technology OR AI OR semiconductor OR startup"},
    {"id": "WORLD",      "ko": "세계", "color": "#fb7185",
     "q_ko": "국제 OR 세계 OR 외교",
     "q_en": "world OR international OR diplomacy"},
]
CATEGORY_IDS = [c["id"] for c in CATEGORIES]
CATEGORY_KO = {c["id"]: c["ko"] for c in CATEGORIES}

# ── 지역 ──
REGIONS = [
    {"id": "KR", "ko": "한국",   "hl": "ko",    "gl": "KR", "ceid": "KR:ko", "lang": "ko"},
    {"id": "US", "ko": "글로벌", "hl": "en-US", "gl": "US", "ceid": "US:en", "lang": "en"},
]
REGION_IDS = [r["id"] for r in REGIONS]
REGION_BY_ID = {r["id"]: r for r in REGIONS}

# ── Google News 토픽 매핑 ──
GOOGLE_TOPICS = {
    "BUSINESS": "BUSINESS",
    "NATION": "NATION",
    "SCIENCE": "SCIENCE",
    "TECHNOLOGY": "TECHNOLOGY",
    "WORLD": "WORLD",
}

# ── 일반 RSS 피드(키 불필요). 필요 시 자유롭게 추가/수정 ──
# (url, category, region, publisher)
GENERIC_FEEDS = [
    # 글로벌 (BBC)
    ("https://feeds.bbci.co.uk/news/business/rss.xml",               "BUSINESS",   "US", "BBC"),
    ("https://feeds.bbci.co.uk/news/science_and_environment/rss.xml","SCIENCE",    "US", "BBC"),
    ("https://feeds.bbci.co.uk/news/technology/rss.xml",             "TECHNOLOGY", "US", "BBC"),
    ("https://feeds.bbci.co.uk/news/world/rss.xml",                  "WORLD",      "US", "BBC"),
    # 글로벌 (기타)
    ("https://www.theverge.com/rss/index.xml",                       "TECHNOLOGY", "US", "The Verge"),
    ("https://feeds.arstechnica.com/arstechnica/technology-lab",     "TECHNOLOGY", "US", "Ars Technica"),
    ("https://www.aljazeera.com/xml/rss/all.xml",                    "WORLD",      "US", "Al Jazeera"),
    # 한국 (연합뉴스)
    ("https://www.yna.co.kr/rss/economy.xml",       "BUSINESS", "KR", "연합뉴스"),
    ("https://www.yna.co.kr/rss/society.xml",       "NATION",   "KR", "연합뉴스"),
    ("https://www.yna.co.kr/rss/internationalnews.xml", "WORLD","KR", "연합뉴스"),
    # 한국 (한겨레)
    ("https://www.hani.co.kr/rss/economy/",  "BUSINESS", "KR", "한겨레"),
    ("https://www.hani.co.kr/rss/society/",  "NATION",   "KR", "한겨레"),
    ("https://www.hani.co.kr/rss/science/",  "SCIENCE",  "KR", "한겨레"),
]
