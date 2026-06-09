"""APScheduler 기반 주기적 수집."""
from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .config import get_settings
from .db import DB
from .ingest import run_ingest
from .trends import clear_cache

log = logging.getLogger("mytrend.scheduler")


class IngestScheduler:
    def __init__(self, db: DB):
        self.db = db
        self.sched = AsyncIOScheduler()
        self.last_result: dict | None = None

    async def _job(self):
        try:
            self.last_result = await run_ingest(self.db)
            clear_cache()  # 새 데이터 반영 위해 캐시 무효화
            log.info("ingest done: %s", self.last_result)
        except Exception as e:
            log.exception("scheduled ingest failed: %s", e)

    def _maintenance(self):
        """일일 유지보수: 최근 며칠 롤업 → 롤업 보존 → 오래된 '기사'만 프루닝."""
        from . import history as H
        try:
            today = H.today_utc()
            for i in range(3):                       # 늦게 들어온 기사 대비 최근 3일 재롤업
                H.rollup_day(self.db, H.day_add(today, -i))
            retention = get_settings().mytrend_article_retention_days
            if retention > 0:
                removed = self.db.prune(retention)   # 롤업(daily_keyword)은 유지, 기사만 삭제
                log.info("maintenance: rolled up + pruned %d old articles (keep %dd)", removed, retention)
            else:
                log.info("maintenance: rolled up; article pruning disabled (keep all, 영구 보존)")
        except Exception as e:
            log.exception("maintenance failed: %s", e)

    def start(self):
        s = get_settings()
        interval = s.mytrend_ingest_interval_min
        if interval > 0:
            self.sched.add_job(self._job, "interval", minutes=interval,
                               id="ingest", max_instances=1, coalesce=True)
            # 매일 새벽 3시: 롤업 + 보존정책(롤업 영구, 기사만 장기 프루닝)
            self.sched.add_job(self._maintenance, "cron", hour=3, id="maintenance")
            self.sched.start()
            log.info("scheduler started (interval=%dmin)", interval)
        if s.mytrend_ingest_on_start:
            asyncio.create_task(self._job())

    def shutdown(self):
        if self.sched.running:
            self.sched.shutdown(wait=False)
