"""scheduler: encola crawls según crawl_interval_hours y recupera jobs colgados."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog
from apscheduler.schedulers.blocking import BlockingScheduler
from sqlalchemy import func, select

from patagonia_land import jobs
from patagonia_land.db.models import CrawlRun, Job, Source
from patagonia_land.db.session import session_scope

log = structlog.get_logger()
STALE_AFTER = timedelta(hours=3)


def enqueue_due_crawls() -> None:
    now = datetime.now(UTC)
    with session_scope() as s:
        for src in s.scalars(select(Source).where(Source.enabled.is_(True))):
            last = s.scalar(select(func.max(CrawlRun.started_at)).where(CrawlRun.source_id == src.id))
            if last is None or now - last >= timedelta(hours=src.crawl_interval_hours):
                job = jobs.enqueue(s, "crawl", src.id)
                log.info("scheduler.enqueued", source=src.id, job_id=job.id)


def recover_stale_jobs() -> None:
    with session_scope() as s:
        for job in s.scalars(select(Job).where(Job.status == "running",
                                               Job.started_at < datetime.now(UTC) - STALE_AFTER)):
            job.status, job.error = "failed", "timeout: job colgado (worker reiniciado?)"


def main() -> None:
    sched = BlockingScheduler(timezone="America/Argentina/Buenos_Aires")
    sched.add_job(enqueue_due_crawls, "interval", minutes=15, next_run_time=datetime.now(UTC))
    sched.add_job(recover_stale_jobs, "interval", minutes=30)
    log.info("scheduler.start")
    sched.start()


if __name__ == "__main__":
    main()
