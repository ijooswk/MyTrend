"""설정·분야·지역·소스 메타데이터 정의."""
from __future__ import annotations

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore",
                                      case_sensitive=False)

    # API 키 (없으면 해당 소스 비활성)
    tavily_api_key: str = ""
    # EODHD 는 EODHD_API_KEY 또는 EODHD_API_TOKEN 둘 다 허용.
    # 두 변수를 따로 받아 '비어있지 않은' 쪽을 사용한다(Docker 가 빈 KEY 를 주입해도 안전).
    eodhd_api_key: str = ""      # EODHD_API_KEY
    eodhd_api_token: str = ""    # EODHD_API_TOKEN
    newsapi_key: str = ""

    @property
    def eodhd_key(self) -> str:
        return (self.eodhd_api_key or self.eodhd_api_token or "").strip()
    # OpenRouter (LLM 게이트웨이) — AI 브리핑·라벨링·Q&A
    openrouter_api_key: str = ""
    mytrend_ai_model: str = "openai/gpt-4o-mini"
    mytrend_ai_max_tokens: int = 700
    mytrend_ai_cache_ttl: int = 600

    # 동작 설정
    mytrend_db_path: str = "mytrend.db"
    mytrend_ingest_interval_min: int = 20
    mytrend_default_hours: int = 24
    mytrend_per_feed_limit: int = 60
    mytrend_cache_ttl: int = 120
    mytrend_ingest_on_start: bool = True
    # 원시 기사 보존 기간(일). 이보다 오래된 '기사'는 프루닝되지만 일별 롤업은 영구 보존.
    mytrend_article_retention_days: int = 120


@lru_cache
def get_settings() -> Settings:
    return Settings()


# ── 분야 (canonical category) ──
# id: 내부코드, ko/en: 라벨, color: 프론트 색, queries: 검색형 소스용 질의(ko/en)
CATEGORIES = [
    {"id": "BUSINESS",   "ko": "경제", "en": "Economy", "color": "#34d399", "selectable": True,
     "q_ko": "경제 OR 금융 OR 증시 OR 산업 OR 부동산",
     "q_en": "economy OR finance OR markets OR business"},
    {"id": "NATION",     "ko": "사회", "en": "Society", "color": "#f59e0b", "selectable": True,
     "q_ko": "사회 OR 사건 OR 사고 OR 정책 OR 노동",
     "q_en": "society OR crime OR policy OR labor"},
    {"id": "SCIENCE",    "ko": "과학", "en": "Science", "color": "#a78bfa", "selectable": True,
     "q_ko": "과학 OR 연구 OR 우주 OR 기후 OR 생명",
     "q_en": "science OR research OR space OR climate"},
    {"id": "TECHNOLOGY", "ko": "테크", "en": "Tech", "color": "#38bdf8", "selectable": True,
     "q_ko": "기술 OR IT OR 인공지능 OR 반도체 OR 스타트업",
     "q_en": "technology OR AI OR semiconductor OR startup"},
    {"id": "WORLD",      "ko": "세계", "en": "World", "color": "#fb7185", "selectable": True,
     "q_ko": "국제 OR 세계 OR 외교",
     "q_en": "world OR international OR diplomacy"},
    {"id": "HEALTH",     "ko": "건강", "en": "Health", "color": "#2dd4bf", "selectable": True,
     "q_ko": "건강 OR 의료 OR 질병 OR 보건 OR 제약",
     "q_en": "health OR medical OR disease OR medicine"},
    {"id": "SPORTS",     "ko": "스포츠", "en": "Sports", "color": "#facc15", "selectable": True,
     "q_ko": "스포츠 OR 축구 OR 야구 OR 올림픽",
     "q_en": "sports OR football OR soccer OR baseball"},
    {"id": "ENTERTAINMENT", "ko": "연예", "en": "Culture", "color": "#f472b6", "selectable": True,
     "q_ko": "연예 OR 영화 OR 음악 OR 드라마 OR 문화",
     "q_en": "entertainment OR movie OR music OR culture"},
]
# 사용자 키워드 검색으로 들어온 기사용 표시 카테고리(선택 불가, 표시 전용)
SEARCH_CATEGORY = {"id": "SEARCH", "ko": "검색", "en": "Search",
                   "color": "#e879f9", "selectable": False}
DISPLAY_CATEGORIES = CATEGORIES + [SEARCH_CATEGORY]

CATEGORY_IDS = [c["id"] for c in CATEGORIES]
CATEGORY_KO = {c["id"]: c["ko"] for c in DISPLAY_CATEGORIES}

# ── 지역 ──
REGIONS = [
    {"id": "KR", "ko": "한국",   "en": "Korea",  "hl": "ko",    "gl": "KR", "ceid": "KR:ko", "lang": "ko"},
    {"id": "US", "ko": "글로벌", "en": "Global", "hl": "en-US", "gl": "US", "ceid": "US:en", "lang": "en"},
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
    "HEALTH": "HEALTH",
    "SPORTS": "SPORTS",
    "ENTERTAINMENT": "ENTERTAINMENT",
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
    # 확장 분야 (BBC)
    ("https://feeds.bbci.co.uk/news/health/rss.xml",                 "HEALTH",        "US", "BBC"),
    ("https://feeds.bbci.co.uk/sport/rss.xml",                       "SPORTS",        "US", "BBC"),
    ("https://feeds.bbci.co.uk/news/entertainment_and_arts/rss.xml", "ENTERTAINMENT", "US", "BBC"),
]
