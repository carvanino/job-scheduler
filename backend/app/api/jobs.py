from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.ws import ws_manager
from app.database import get_db
from app.logger import get_logger
from app.models import DeadLetterJob, Job, JobDependency, JobLog
from app.scheduler.dag import has_cycle
from app.schemas import JobCreate, JobLogResponse, JobResponse, JobStats

log = get_logger(__name__)
router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("", status_code=201, response_model=JobResponse)
async def create_job(body: JobCreate, db: AsyncSession = Depends(get_db)):
    # Cycle detection for DAG
    if body.dependency_ids:
        for dep_id in body.dependency_ids:
            parent = await db.get(Job, dep_id)
            if parent is None:
                raise HTTPException(status_code=404, detail=f"Dependency job {dep_id} not found")

    job = Job(
        type=body.type,
        payload=body.payload,
        priority=body.priority,
        scheduled_at=body.scheduled_at,
        recurring_interval=body.recurring_interval,
        effective_priority=float(body.priority),
    )
    db.add(job)
    await db.flush()  # get the job.id before adding dependencies

    # Cycle check
    if body.dependency_ids:
        if await has_cycle(job.id, body.dependency_ids, db):
            await db.rollback()
            raise HTTPException(status_code=400, detail="Circular dependency detected")
        for dep_id in body.dependency_ids:
            db.add(JobDependency(job_id=job.id, depends_on_id=dep_id))

    db.add(JobLog(
        job_id=job.id,
        event="created",
        message=f"Job created (type={body.type}, priority={body.priority})",
        data={
            "type": body.type,
            "priority": body.priority,
            "dependency_count": len(body.dependency_ids),
        },
    ))
    await db.commit()
    await db.refresh(job)

    log.info("job.created", job_id=str(job.id), type=job.type, priority=job.priority)
    await ws_manager.broadcast("job_update", {
        "job_id": str(job.id),
        "status": "pending",
        "type": job.type,
    })

    return job


@router.get("", response_model=list[JobResponse])
async def list_jobs(
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    q = select(Job).order_by(Job.created_at.desc()).limit(limit).offset(offset)
    if status:
        q = q.where(Job.status == status)
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/stats", response_model=JobStats)
async def get_stats(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Job.status, func.count().label("count")).group_by(Job.status)
    )
    counts = {r.status: r.count for r in result.all()}
    dlq_result = await db.execute(select(func.count()).select_from(DeadLetterJob))
    dlq_count = dlq_result.scalar_one()
    total = sum(counts.values())
    return JobStats(
        pending=counts.get("pending", 0),
        processing=counts.get("processing", 0),
        completed=counts.get("completed", 0),
        failed=counts.get("failed", 0),
        cancelled=counts.get("cancelled", 0),
        total=total,
        dlq=dlq_count,
    )


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(job_id: UUID, db: AsyncSession = Depends(get_db)):
    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/{job_id}/cancel", response_model=JobResponse)
async def cancel_job(job_id: UUID, db: AsyncSession = Depends(get_db)):
    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status in ("completed", "failed", "cancelled"):
        raise HTTPException(status_code=400, detail=f"Cannot cancel a job with status '{job.status}'")

    # If already processing: mark cancelled but let the worker finish its
    # current attempt — it will see the status on its next DB check and stop.
    # This is a best-effort cancellation documented in the architecture doc.
    prev_status = job.status
    job.status = "cancelled"
    job.updated_at = datetime.now(timezone.utc)
    db.add(JobLog(
        job_id=job.id,
        event="cancelled",
        message=f"Job cancelled (was {prev_status})",
        data={"previous_status": prev_status},
    ))
    await db.commit()
    await db.refresh(job)

    log.info("job.cancelled", job_id=str(job.id), previous_status=prev_status)
    await ws_manager.broadcast("job_update", {"job_id": str(job.id), "status": "cancelled"})
    return job


@router.get("/{job_id}/logs", response_model=list[JobLogResponse])
async def get_job_logs(job_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(JobLog)
        .where(JobLog.job_id == job_id)
        .order_by(JobLog.created_at.asc())
    )
    return result.scalars().all()
