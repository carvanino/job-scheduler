from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.ws import ws_manager
from app.database import get_db
from app.logger import get_logger
from app.models import DeadLetterJob, Job, JobLog
from app.schemas import DLQEntry

log = get_logger(__name__)
router = APIRouter(prefix="/dlq", tags=["dlq"])


@router.get("", response_model=list[DLQEntry])
async def list_dlq(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(DeadLetterJob)
        .options(selectinload(DeadLetterJob.job))
        .order_by(DeadLetterJob.moved_at.desc())
    )
    return result.scalars().all()


@router.post("/{dlq_id}/retry", response_model=DLQEntry)
async def retry_dlq_job(dlq_id: UUID, db: AsyncSession = Depends(get_db)):
    """
    Manually re-queue a DLQ job for another attempt.
    Resets status to pending, clears retry_count, and re-queues.
    If it fails again, it returns to the DLQ.
    """
    entry = await db.get(DeadLetterJob, dlq_id, options=[selectinload(DeadLetterJob.job)])
    if entry is None:
        raise HTTPException(status_code=404, detail="DLQ entry not found")

    job = entry.job
    job.status = "pending"
    job.retry_count = 0
    job.last_error = None
    job.scheduled_at = None
    job.locked_at = None
    job.locked_by = None
    job.updated_at = datetime.now(timezone.utc)

    entry.retried_at = datetime.now(timezone.utc)

    db.add(JobLog(
        job_id=job.id,
        event="dlq_retry",
        message="Manual retry triggered from DLQ",
        data={"dlq_id": str(dlq_id)},
    ))
    await db.commit()
    await db.refresh(entry)

    log.info("dlq.retry_triggered", job_id=str(job.id), dlq_id=str(dlq_id))
    await ws_manager.broadcast("job_update", {"job_id": str(job.id), "status": "pending"})
    return entry
