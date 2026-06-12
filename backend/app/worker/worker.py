"""
Worker — polls the scheduler, executes jobs, handles retries and DLQ.

The worker loop runs every WORKER_POLL_INTERVAL (0.5s) and:
  1. Loads due jobs from the DB into the IndexedPriorityQueue
  2. Runs starvation checks on the IndexedPriorityQueue
  3. Peeks at the highest-priority job
  4. Checks DAG dependencies — skips if blocked
  5. Locks the job in DB using SELECT FOR UPDATE SKIP LOCKED
     (prevents two workers picking the same job)
  6. Marks the job as processing
  7. Calls the appropriate handler
  8. On success: marks completed, schedules next run if recurring
  9. On failure: applies retry logic or moves to DLQ
 10. Broadcasts status change via WebSocket

Retry backoff (with jitter multiplier in [0.8, 1.2)):
  Attempt 1 → base ~1s
  Attempt 2 → base ~5s
  Attempt 3 → base ~25s
  Attempt 4 → DLQ

DLQ threshold alert: when DLQ crosses settings.DLQ_ALERT_THRESHOLD,
an alert is logged (and in production would trigger an email).
"""

from __future__ import annotations

import asyncio
import random
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal
from app.handlers.webhook import WebhookTerminalError, WebhookTransientError, handle as webhook_handle
from app.logger import get_logger
from app.models import DeadLetterJob, Job, JobLog
from app.scheduler.dag import can_run, should_propagate_failure
from app.scheduler.indexed_pq import IndexedPriorityQueue
from app.scheduler.starvation import compute_effective_priority, run_starvation_check
from app.scheduler.heap import JobEntry

log = get_logger(__name__)

# Backoff base delays in seconds for each retry attempt (1-indexed)
BACKOFF_BASE = {1: 1.0, 2: 5.0, 3: 25.0}

# Recurring interval → timedelta map
INTERVAL_MAP = {
    "every_1_minute": timedelta(minutes=1),
    "every_5_minutes": timedelta(minutes=5),
    "every_1_hour": timedelta(hours=1),
}


def _backoff_delay(attempt: int) -> float:
    """
    Exponential backoff with jitter.
    attempt is 1-indexed (first retry = attempt 1).
    """
    base = BACKOFF_BASE.get(attempt, 25.0)
    jitter = random.uniform(0.8, 1.2)
    return base * jitter


class Worker:
    def __init__(self, worker_id: str, ipq: IndexedPriorityQueue, ws_broadcast) -> None:
        self.worker_id = worker_id
        self.ipq = ipq
        self.ws_broadcast = ws_broadcast
        self._job_meta: dict[str, dict] = {}  # job_id → {priority, created_at}
        self._running = False
        self._last_starvation_check = datetime.now(timezone.utc)

    async def start(self) -> None:
        self._running = True
        log.info("worker.started", worker_id=self.worker_id)
        await self._loop()

    async def stop(self) -> None:
        self._running = False
        log.info("worker.stopped", worker_id=self.worker_id)

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.exception("worker.loop_error", worker_id=self.worker_id, error=str(exc))
            await asyncio.sleep(settings.WORKER_POLL_INTERVAL)

    async def _tick(self) -> None:
        # 1. Load due jobs from DB into the IPQ
        await self._load_due_jobs()

        # 2. Run starvation check periodically
        now = datetime.now(timezone.utc)
        elapsed = (now - self._last_starvation_check).total_seconds()
        if elapsed >= settings.STARVATION_CHECK_INTERVAL:
            boosted = run_starvation_check(self.ipq, self._job_meta)
            if boosted:
                log.info("starvation.check_complete", boosted_count=len(boosted))
            self._last_starvation_check = now

        # 3. Nothing in queue
        entry = self.ipq.peek()
        if entry is None:
            return

        # 4. Check DAG dependencies
        async with AsyncSessionLocal() as db:
            job_uuid = UUID(entry.job_id)

            if await should_propagate_failure(job_uuid, db):
                self.ipq.remove(entry.job_id)
                self._job_meta.pop(entry.job_id, None)
                job = await db.get(Job, job_uuid)
                if job and job.status == "pending":
                    await self._fail_job(job, "Dependency failed or was cancelled", db, terminal=True)
                return

            if not await can_run(job_uuid, db):
                # Dependencies not done yet — skip this cycle, leave in queue
                return

        # 5. Try to lock the job (SKIP LOCKED prevents duplicate pickup)
        async with AsyncSessionLocal() as db:
            job = await self._lock_job(UUID(entry.job_id), db)
            if job is None:
                # Another worker grabbed it
                self.ipq.remove(entry.job_id)
                self._job_meta.pop(entry.job_id, None)
                return

        # 6. Pop from queue now that we own it
        self.ipq.remove(entry.job_id)
        self._job_meta.pop(entry.job_id, None)

        # 7. Execute
        await self._execute(job)

    async def _load_due_jobs(self) -> None:
        """
        Query DB for pending jobs whose scheduled_at <= now and load
        them into the IPQ if not already present.
        """
        now = datetime.now(timezone.utc)
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Job)
                .where(Job.status == "pending")
                .where(
                    (Job.scheduled_at == None) | (Job.scheduled_at <= now)  # noqa: E711
                )
                .limit(100)
            )
            jobs = result.scalars().all()

        for job in jobs:
            if job.id and str(job.id) not in self.ipq:
                ep = compute_effective_priority(job.priority, job.created_at)
                entry = JobEntry(
                    job_id=str(job.id),
                    effective_priority=ep,
                    scheduled_at=job.scheduled_at or job.created_at,
                    created_at=job.created_at,
                    job_type=job.type,
                )
                self.ipq.push(entry)
                self._job_meta[str(job.id)] = {
                    "priority": job.priority,
                    "created_at": job.created_at,
                }

    async def _lock_job(self, job_id: UUID, db: AsyncSession) -> Job | None:
        """
        Attempt to lock a job using SELECT FOR UPDATE SKIP LOCKED.
        If another worker already locked it, returns None.
        """
        result = await db.execute(
            select(Job)
            .where(Job.id == job_id)
            .where(Job.status == "pending")
            .with_for_update(skip_locked=True)
        )
        job = result.scalar_one_or_none()
        if job is None:
            return None

        job.status = "processing"
        job.locked_at = datetime.now(timezone.utc)
        job.locked_by = self.worker_id
        job.updated_at = datetime.now(timezone.utc)

        db.add(JobLog(
            job_id=job.id,
            event="started",
            message=f"Worker {self.worker_id} picked up job",
            data={"worker_id": self.worker_id},
        ))
        await db.commit()
        await db.refresh(job)
        log.info("job.started", job_id=str(job.id), worker_id=self.worker_id, type=job.type)
        await self.ws_broadcast("job_update", {"job_id": str(job.id), "status": "processing"})
        return job

    async def _execute(self, job: Job) -> None:
        """Dispatch to the appropriate handler based on job.type."""
        try:
            if job.type == "webhook":
                result = await webhook_handle(job.payload)
            else:
                raise ValueError(f"Unknown job type: {job.type}")

            await self._complete_job(job, result)

        except WebhookTerminalError as exc:
            # 4xx — do not retry, move straight to failed
            log.warning("job.terminal_failure", job_id=str(job.id), error=str(exc))
            async with AsyncSessionLocal() as db:
                j = await db.get(Job, job.id)
                if j:
                    await self._fail_job(j, str(exc), db, terminal=True)

        except (WebhookTransientError, Exception) as exc:
            # Transient — attempt retry
            log.warning("job.transient_failure", job_id=str(job.id), error=str(exc))
            async with AsyncSessionLocal() as db:
                j = await db.get(Job, job.id)
                if j:
                    await self._retry_or_dlq(j, str(exc), db)

    async def _complete_job(self, job: Job, result: dict) -> None:
        async with AsyncSessionLocal() as db:
            j = await db.get(Job, job.id)
            if j is None:
                return
            now = datetime.now(timezone.utc)
            j.status = "completed"
            j.result = result
            j.completed_at = now
            j.updated_at = now
            j.locked_at = None
            j.locked_by = None

            db.add(JobLog(
                job_id=j.id,
                event="completed",
                message="Job completed successfully",
                data=result,
            ))

            # Schedule next run for recurring jobs
            if j.recurring_interval:
                delta = INTERVAL_MAP.get(j.recurring_interval)
                if delta:
                    j.next_run_at = now + delta
                    await self._schedule_next_run(j, db)

            await db.commit()

        log.info("job.completed", job_id=str(job.id), type=job.type)
        await self.ws_broadcast("job_update", {"job_id": str(job.id), "status": "completed"})
        await self._broadcast_stats()

    async def _retry_or_dlq(self, job: Job, error: str, db: AsyncSession) -> None:
        job.retry_count += 1
        job.last_error = error
        job.updated_at = datetime.now(timezone.utc)

        if job.retry_count > job.max_retries:
            await self._move_to_dlq(job, error, db)
        else:
            delay = _backoff_delay(job.retry_count)
            job.status = "pending"
            job.scheduled_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
            job.locked_at = None
            job.locked_by = None

            db.add(JobLog(
                job_id=job.id,
                event="retry",
                message=f"Retry {job.retry_count}/{job.max_retries} in {delay:.1f}s",
                data={"retry_count": job.retry_count, "delay_seconds": round(delay, 2), "error": error},
            ))
            await db.commit()

            log.info(
                "job.retry_scheduled",
                job_id=str(job.id),
                attempt=job.retry_count,
                delay_seconds=round(delay, 2),
            )
            await self.ws_broadcast("job_update", {
                "job_id": str(job.id),
                "status": "pending",
                "retry_count": job.retry_count,
            })

    async def _fail_job(self, job: Job, error: str, db: AsyncSession, terminal: bool = False) -> None:
        job.status = "failed"
        job.last_error = error
        job.updated_at = datetime.now(timezone.utc)
        job.locked_at = None
        job.locked_by = None
        db.add(JobLog(
            job_id=job.id,
            event="failed",
            message=error,
            data={"terminal": terminal},
        ))
        await db.commit()
        log.warning("job.failed", job_id=str(job.id), error=error, terminal=terminal)
        await self.ws_broadcast("job_update", {"job_id": str(job.id), "status": "failed"})
        await self._broadcast_stats()

    async def _move_to_dlq(self, job: Job, error: str, db: AsyncSession) -> None:
        job.status = "failed"
        job.last_error = error
        job.updated_at = datetime.now(timezone.utc)
        job.locked_at = None
        job.locked_by = None

        # Check if a DLQ entry already exists for this job (happens when a
        # manually-retried job fails again). Update it rather than inserting
        # a duplicate — job_id has a unique constraint.
        existing = await db.execute(
            select(DeadLetterJob).where(DeadLetterJob.job_id == job.id)
        )
        dlq_entry = existing.scalar_one_or_none()
        if dlq_entry:
            dlq_entry.error = error
            dlq_entry.retry_count = job.retry_count
            dlq_entry.moved_at = datetime.now(timezone.utc)
            dlq_entry.retried_at = None
        else:
            dlq_entry = DeadLetterJob(
                job_id=job.id,
                error=error,
                retry_count=job.retry_count,
            )
            db.add(dlq_entry)

        db.add(JobLog(
            job_id=job.id,
            event="dlq_moved",
            message=f"Exhausted {job.retry_count} retries — moved to DLQ",
            data={"error": error},
        ))
        await db.commit()

        log.warning("job.dlq_moved", job_id=str(job.id), retry_count=job.retry_count)
        await self.ws_broadcast("job_update", {"job_id": str(job.id), "status": "failed"})

        # DLQ threshold alert
        await self._check_dlq_threshold(db)
        await self._broadcast_stats()

    async def _check_dlq_threshold(self, db: AsyncSession) -> None:
        from sqlalchemy import func
        result = await db.execute(select(func.count()).select_from(DeadLetterJob))
        count = result.scalar_one()
        if count >= settings.DLQ_ALERT_THRESHOLD:
            log.error(
                "dlq.threshold_exceeded",
                count=count,
                threshold=settings.DLQ_ALERT_THRESHOLD,
                alert_email=settings.ALERT_EMAIL,
                message=f"DLQ has {count} jobs — alert sent to {settings.ALERT_EMAIL}",
            )
            await self.ws_broadcast("dlq_alert", {
                "count": count,
                "threshold": settings.DLQ_ALERT_THRESHOLD,
            })

    async def _schedule_next_run(self, job: Job, db: AsyncSession) -> None:
        """Create a new job record for the next recurring run."""
        next_job = Job(
            type=job.type,
            payload=job.payload,
            priority=job.priority,
            scheduled_at=job.next_run_at,
            recurring_interval=job.recurring_interval,
            effective_priority=float(job.priority),
        )
        db.add(next_job)
        await db.flush()  # materialise next_job.id before JobLog references it
        db.add(JobLog(
            job_id=next_job.id,
            event="created",
            message=f"Recurring job auto-scheduled (interval: {job.recurring_interval})",
            data={"parent_job_id": str(job.id), "scheduled_at": job.next_run_at.isoformat()},
        ))
        log.info(
            "job.recurring_scheduled",
            parent_job_id=str(job.id),
            next_run_at=job.next_run_at.isoformat(),
            interval=job.recurring_interval,
        )

    async def _broadcast_stats(self) -> None:
        from sqlalchemy import func
        from app.models import DeadLetterJob
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Job.status, func.count().label("count"))
                .group_by(Job.status)
            )
            rows = result.all()
            counts = {r.status: r.count for r in rows}
            dlq_result = await db.execute(select(func.count()).select_from(DeadLetterJob))
            dlq_count = dlq_result.scalar_one()

        await self.ws_broadcast("stats_update", {
            "pending": counts.get("pending", 0),
            "processing": counts.get("processing", 0),
            "completed": counts.get("completed", 0),
            "failed": counts.get("failed", 0),
            "cancelled": counts.get("cancelled", 0),
            "dlq": dlq_count,
        })
