"""scheduler: encola crawls según crawl_interval_hours y recupera jobs colgados."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog
from apscheduler.schedulers.blocking import BlockingScheduler
from sqlalchemy import func, or_, select

from patagonia_land import jobs
from patagonia_land.db.models import CrawlRun, Job, Source
from patagonia_land.db.session import session_scope

log = structlog.get_logger()
STALE_AFTER = timedelta(hours=5)  # > máx. de una corrida (4 h, fuentes lentas por robots.txt)


def enqueue_due_crawls() -> None:
    now = datetime.now(UTC)
    with session_scope() as s:
        for src in s.scalars(select(Source).where(Source.enabled.is_(True))):
            last = s.scalar(select(func.max(CrawlRun.started_at)).where(CrawlRun.source_id == src.id))
            if last is None or now - last >= timedelta(hours=src.crawl_interval_hours):
                job = jobs.enqueue(s, "crawl", src.id)
                log.info("scheduler.enqueued", source=src.id, job_id=job.id)


def enqueue_geo() -> None:
    """Tiempos de manejo a BRC/CPC/EQS (requiere ORS_API_KEY; sin clave el job no hace llamadas)."""
    with session_scope() as s:
        jobs.enqueue(s, "geo", None)


def recover_stale_jobs() -> None:
    with session_scope() as s:
        for job in s.scalars(select(Job).where(Job.status == "running",
                                               Job.started_at < datetime.now(UTC) - STALE_AFTER)):
            job.status, job.error = "failed", "timeout: job colgado (worker reiniciado?)"
        # Corridas que quedaron "running" cuando su job ya terminó o falló (p. ej. worker reiniciado en un deploy).
        for run in s.scalars(select(CrawlRun).outerjoin(Job, CrawlRun.job_id == Job.id).where(
                CrawlRun.status == "running", or_(Job.id.is_(None), Job.status != "running"),
                CrawlRun.started_at < datetime.now(UTC) - timedelta(minutes=30))):
            run.status, run.finished_at = "failed", run.finished_at or datetime.now(UTC)


def main() -> None:
    sched = BlockingScheduler(timezone="America/Argentina/Buenos_Aires")
    sched.add_job(enqueue_due_crawls, "interval", minutes=15, next_run_time=datetime.now(UTC))
    sched.add_job(recover_stale_jobs, "interval", minutes=30)
    sched.add_job(enqueue_geo, "interval", hours=6, next_run_time=datetime.now(UTC) + timedelta(minutes=5))
    log.info("scheduler.start")
    sched.start()


if __name__ == "__main__":
    main()
