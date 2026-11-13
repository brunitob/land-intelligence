"""Cola de jobs en PostgreSQL (SELECT ... FOR UPDATE SKIP LOCKED). Sin broker extra."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from patagonia_land.db.models import Job

ACTIVE = ("queued", "running")


def enqueue(session: Session, kind: str, source_id: str | None) -> Job:
    """Idempotente: si ya hay un job igual pendiente/en curso, devuelve ese."""
    existing = session.scalar(select(Job).where(Job.kind == kind, Job.source_id == source_id,
                                                Job.status.in_(ACTIVE)))
    if existing:
        return existing
    job = Job(kind=kind, source_id=source_id, status="queued", progress={})
    session.add(job)
    session.flush()
    return job


def claim_next(session: Session) -> Job | None:
    job = session.scalar(select(Job).where(Job.status == "queued").order_by(Job.created_at)
                         .with_for_update(skip_locked=True).limit(1))
    if job:
        job.status = "running"
        job.started_at = datetime.now(UTC)
        session.flush()
    return job


def finish(session: Session, job_id: int, result: dict[str, Any] | None = None, error: str | None = None) -> None:
    job = session.get(Job, job_id)
    if not job:
        return
    job.status = "failed" if error else "done"
    job.result = result
    job.error = error
    job.finished_at = datetime.now(UTC)
