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

    def start(self):
        s = get_settings()
        interval = s.mytrend_ingest_interval_min
        if interval > 0:
            self.sched.add_job(self._job, "interval", minutes=interval,
                               id="ingest", max_instances=1, coalesce=True)
            # 매일 새벽 4시 오래된 기사 정리
            self.sched.add_job(lambda: self.db.prune(7), "cron", hour=4, id="prune")
            self.sched.start()
            log.info("scheduler started (interval=%dmin)", interval)
        if s.mytrend_ingest_on_start:
            asyncio.create_task(self._job())

    def shutdown(self):
        if self.sched.running:
            self.sched.shutdown(wait=False)
