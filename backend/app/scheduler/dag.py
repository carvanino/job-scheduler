"""
DAG dependency resolver.

A job can declare that it depends on other jobs via the job_dependencies table.
The scheduler checks this before allowing a job to enter the processing state.

Example workflow:
  generate_report → upload_file → send_email

  upload_file declares: depends_on = [generate_report.id]
  send_email  declares: depends_on = [upload_file.id]

Rules:
  - A job only runs when ALL its dependencies have status='completed'.
  - If any dependency has status='failed' or 'cancelled', the dependent job
    is also marked failed (propagated failure).
  - Circular dependencies are detected at job creation time.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logger import get_logger
from app.models import Job, JobDependency

log = get_logger(__name__)


async def can_run(job_id: UUID, db: AsyncSession) -> bool:
    """
    Return True if all dependencies of this job have completed successfully.
    Return False if any dependency is still pending/processing.
    """
    result = await db.execute(
        select(JobDependency).where(JobDependency.job_id == job_id)
    )
    dependencies = result.scalars().all()

    if not dependencies:
        return True  # no dependencies, free to run

    for dep in dependencies:
        parent = await db.get(Job, dep.depends_on_id)
        if parent is None:
            log.warning("dag.dependency_missing", job_id=str(job_id), dep_id=str(dep.depends_on_id))
            return False
        if parent.status != "completed":
            return False

    return True


async def should_propagate_failure(job_id: UUID, db: AsyncSession) -> bool:
    """
    Return True if any dependency has failed or been cancelled.
    The caller should mark this job as failed when this returns True.
    """
    result = await db.execute(
        select(JobDependency).where(JobDependency.job_id == job_id)
    )
    dependencies = result.scalars().all()

    for dep in dependencies:
        parent = await db.get(Job, dep.depends_on_id)
        if parent and parent.status in ("failed", "cancelled"):
            log.info(
                "dag.failure_propagated",
                job_id=str(job_id),
                failed_dep=str(dep.depends_on_id),
                dep_status=parent.status,
            )
            return True

    return False


async def has_cycle(job_id: UUID, dependency_ids: list[UUID], db: AsyncSession) -> bool:
    """
    Detect if adding these dependencies would create a cycle.
    Uses iterative DFS on the existing dependency graph.
    """
    # Build the set of all ancestors of job_id via existing dependencies
    visited: set[UUID] = set()
    stack: list[UUID] = list(dependency_ids)

    while stack:
        current = stack.pop()
        if current == job_id:
            return True   # cycle detected
        if current in visited:
            continue
        visited.add(current)

        result = await db.execute(
            select(JobDependency).where(JobDependency.job_id == current)
        )
        for dep in result.scalars().all():
            stack.append(dep.depends_on_id)

    return False
