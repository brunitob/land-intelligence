"""scraper-worker: toma jobs de la cola y los ejecuta (uno a la vez por proceso)."""

from __future__ import annotations

import asyncio
import signal
import traceback

import structlog

from patagonia_land import jobs
from patagonia_land.db.session import session_scope
from patagonia_land.geo.routing import run_geo
from patagonia_land.pipeline import run_crawl, run_inspect
from patagonia_land.watch import run_watch

log = structlog.get_logger()
_stop = False


def _handle(*_: object) -> None:
    global _stop
    _stop = True


async def run_job(job_id: int, kind: str, source_id: str | None) -> None:
    try:
        if kind == "inspect":
            result = await run_inspect(source_id, job_id)
        elif kind == "crawl":
            result = await run_crawl(source_id, job_id)
        elif kind == "watch":
            result = await run_watch(job_id)
        elif kind == "geo":
            result = await asyncio.to_thread(run_geo)
        else:
            raise ValueError(f"tipo de job desconocido: {kind}")
        with session_scope() as s:
            jobs.finish(s, job_id, result=result)
    except jobs.Deferred as d:
        log.info("job.deferred", job_id=job_id, until=d.until.isoformat(), reason=d.reason)
        with session_scope() as s:
            jobs.defer(s, job_id, d.until, d.reason)
    except Exception as exc:
        log.error("job.failed", job_id=job_id, error=repr(exc), tb=traceback.format_exc())
        with session_scope() as s:
            jobs.finish(s, job_id, error=f"{exc!r}"[:2000])


async def main() -> None:
    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)
    log.info("worker.start")
    while not _stop:
        with session_scope() as s:
            job = jobs.claim_next(s)
            claimed = (job.id, job.kind, job.source_id) if job else None
        if not claimed:
            await asyncio.sleep(3)
            continue
        log.info("job.start", job_id=claimed[0], kind=claimed[1], source=claimed[2])
        await run_job(*claimed)


if __name__ == "__main__":
    asyncio.run(main())
