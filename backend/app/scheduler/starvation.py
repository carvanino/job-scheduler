"""
Starvation prevention — priority aging.

The scheduler runs this every STARVATION_CHECK_INTERVAL seconds.
For each pending job in the indexed priority queue, effective_priority
is lowered (more urgent) based on how long the job has been waiting.

Thresholds (configurable via settings):
  Low priority (3)    → boost starts after STARVATION_LOW_MINUTES (default: 5 min)
  Medium priority (2) → boost starts after STARVATION_MEDIUM_MINUTES (default: 10 min)
  Any priority        → reaches effective_priority=1.0 after STARVATION_MAX_MINUTES (15 min)

The formula is linear interpolation:
  boost_factor = minutes_waiting / starvation_max_minutes
  effective_priority = original_priority - (original_priority - 1.0) * boost_factor

Examples:
  Low job (p=3), waiting 15 min:
    factor = 15/15 = 1.0
    effective = 3 - (3-1) * 1.0 = 1.0   ← treated as High priority now

  Low job (p=3), waiting 7.5 min:
    factor = 7.5/15 = 0.5
    effective = 3 - (3-1) * 0.5 = 2.0   ← treated as Medium priority

  High job (p=1): never boosted (already highest)
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.config import settings
from app.logger import get_logger
from app.scheduler.indexed_pq import IndexedPriorityQueue

log = get_logger(__name__)


def compute_effective_priority(
    original_priority: int,
    created_at: datetime,
    now: datetime | None = None,
) -> float:
    """
    Compute the current effective priority for a job based on how long
    it has been waiting. Returns a value in [1.0, original_priority].
    """
    if original_priority == 1:
        return 1.0  # already highest, no boost needed

    if now is None:
        now = datetime.now(timezone.utc)

    # Ensure both are timezone-aware
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)

    minutes_waiting = (now - created_at).total_seconds() / 60.0

    # Below threshold: no boost yet
    threshold = (
        settings.STARVATION_LOW_MINUTES
        if original_priority == 3
        else settings.STARVATION_MEDIUM_MINUTES
    )
    if minutes_waiting < threshold:
        return float(original_priority)

    # Linear interpolation toward 1.0
    max_minutes = float(settings.STARVATION_MAX_MINUTES)
    factor = min(minutes_waiting / max_minutes, 1.0)
    effective = original_priority - (original_priority - 1.0) * factor
    return max(effective, 1.0)


def run_starvation_check(
    ipq: IndexedPriorityQueue,
    job_meta: dict[str, dict],  # job_id → {priority, created_at}
) -> list[str]:
    """
    Iterate over all jobs in the indexed priority queue and update any
    whose effective_priority has changed due to waiting time.

    Returns list of job_ids that were boosted.

    This is the operation where IndexedPQ's O(log n) update_priority beats
    the plain heap's O(n) scan. At 500 pending jobs:
      Plain heap: 500 * 500 = 250,000 comparisons per cycle
      IndexedPQ:  500 * log(500) ≈ 4,500 comparisons per cycle
    """
    boosted: list[str] = []
    now = datetime.now(timezone.utc)

    for job_id, meta in job_meta.items():
        if job_id not in ipq:
            continue
        new_ep = compute_effective_priority(meta["priority"], meta["created_at"], now)
        pos = ipq._index.get(job_id)
        if pos is None:
            continue
        current_ep = ipq._heap[pos].effective_priority
        if abs(new_ep - current_ep) > 0.01:
            ipq.update_priority(job_id, new_ep)
            boosted.append(job_id)
            log.info(
                "starvation.priority_boosted",
                job_id=job_id,
                old_priority=current_ep,
                new_priority=new_ep,
                minutes_waiting=round((now - meta["created_at"]).total_seconds() / 60, 1),
            )

    return boosted
