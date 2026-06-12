"""
benchmark.py — MinHeap vs IndexedPriorityQueue

Measures the cost of the two operations that differ between the algorithms:
  1. update_priority — used by starvation prevention every 30 seconds
  2. remove         — used by job cancellation

Run:
    cd backend
    python benchmark.py

Expected output (example on 10,000 jobs):
    --- update_priority (10000 jobs, 1000 updates) ---
    MinHeap (scan + rebuild): 412.3 ms
    IndexedPQ (index lookup): 2.1 ms
    Speedup: 196x

    --- remove by id (10000 jobs, 500 removals) ---
    MinHeap (linear scan):    198.4 ms
    IndexedPQ (index lookup): 1.1 ms
    Speedup: 180x

The speedup comes from:
  MinHeap.update_priority = O(n) scan to find + O(log n) bubble = O(n) dominated
  IndexedPQ.update_priority = O(1) index lookup + O(log n) bubble = O(log n)

At 10,000 jobs that is roughly 10,000 operations vs 13 per update.
"""

import random
import time
from datetime import datetime, timezone

from app.scheduler.heap import JobEntry, MinHeap
from app.scheduler.indexed_pq import IndexedPriorityQueue


def make_entries(n: int) -> list[JobEntry]:
    now = datetime.now(timezone.utc)
    return [
        JobEntry(
            job_id=f"job-{i}",
            effective_priority=float(random.choice([1, 2, 3])),
            scheduled_at=now,
            created_at=now,
            job_type="webhook",
        )
        for i in range(n)
    ]


# ── Benchmark 1: update_priority ────────────────────────────────

def bench_heap_update(entries: list[JobEntry], updates: int) -> float:
    """
    MinHeap update: scan the array to find the job (O(n)),
    update the value, remove and re-insert to fix order (O(log n)).
    Total: O(n).
    """
    heap = MinHeap()
    for e in entries:
        heap.push(e)

    ids = [e.job_id for e in random.sample(entries, updates)]
    start = time.perf_counter()
    for job_id in ids:
        # Simulate what starvation prevention must do on a plain heap:
        # 1. Linear scan to find it
        found = None
        for entry in heap._heap:
            if entry.job_id == job_id:
                found = entry
                break
        if found:
            # 2. Remove it (linear scan again internally)
            heap.remove_by_id(job_id)
            # 3. Re-insert with new priority
            found.effective_priority = 1.0
            heap.push(found)
    return (time.perf_counter() - start) * 1000


def bench_ipq_update(entries: list[JobEntry], updates: int) -> float:
    """
    IndexedPQ update: O(1) lookup + O(log n) bubble. Total: O(log n).
    """
    ipq = IndexedPriorityQueue()
    for e in entries:
        ipq.push(e)

    ids = [e.job_id for e in random.sample(entries, updates)]
    start = time.perf_counter()
    for job_id in ids:
        ipq.update_priority(job_id, 1.0)
    return (time.perf_counter() - start) * 1000


# ── Benchmark 2: remove ─────────────────────────────────────────

def bench_heap_remove(entries: list[JobEntry], removals: int) -> float:
    heap = MinHeap()
    for e in entries:
        heap.push(e)
    ids = [e.job_id for e in random.sample(entries, removals)]
    start = time.perf_counter()
    for job_id in ids:
        heap.remove_by_id(job_id)   # O(n) scan
    return (time.perf_counter() - start) * 1000


def bench_ipq_remove(entries: list[JobEntry], removals: int) -> float:
    ipq = IndexedPriorityQueue()
    for e in entries:
        ipq.push(e)
    ids = [e.job_id for e in random.sample(entries, removals)]
    start = time.perf_counter()
    for job_id in ids:
        ipq.remove(job_id)          # O(log n)
    return (time.perf_counter() - start) * 1000


# ── Benchmark 3: push + pop (both should be equal) ──────────────

def bench_push_pop(entries: list[JobEntry], cls) -> float:
    q = cls()
    start = time.perf_counter()
    for e in entries:
        q.push(e)
    while q.peek():
        q.pop()
    return (time.perf_counter() - start) * 1000


# ── Run ─────────────────────────────────────────────────────────

def run(n: int = 10_000, updates: int = 1_000, removals: int = 500) -> None:
    print(f"\nBenchmark: {n:,} jobs, {updates:,} priority updates, {removals:,} removals")
    print("=" * 60)

    entries = make_entries(n)

    # update_priority
    heap_update_ms = bench_heap_update(entries, updates)
    ipq_update_ms  = bench_ipq_update(entries, updates)
    speedup_update = heap_update_ms / ipq_update_ms if ipq_update_ms > 0 else float("inf")

    print(f"\n[update_priority — starvation prevention]")
    print(f"  MinHeap  (O(n) scan):         {heap_update_ms:>8.2f} ms")
    print(f"  IndexedPQ (O(log n) lookup):  {ipq_update_ms:>8.2f} ms")
    print(f"  Speedup:                      {speedup_update:>8.1f}x")

    # remove
    heap_remove_ms = bench_heap_remove(entries, removals)
    ipq_remove_ms  = bench_ipq_remove(entries, removals)
    speedup_remove = heap_remove_ms / ipq_remove_ms if ipq_remove_ms > 0 else float("inf")

    print(f"\n[remove — cancellation]")
    print(f"  MinHeap  (O(n) scan):         {heap_remove_ms:>8.2f} ms")
    print(f"  IndexedPQ (O(log n) lookup):  {ipq_remove_ms:>8.2f} ms")
    print(f"  Speedup:                      {speedup_remove:>8.1f}x")

    # push + pop (baseline — both should be O(n log n))
    heap_pp_ms = bench_push_pop(make_entries(n), MinHeap)
    ipq_pp_ms  = bench_push_pop(make_entries(n), IndexedPriorityQueue)

    print(f"\n[push + pop all — baseline (both O(n log n))]")
    print(f"  MinHeap:                      {heap_pp_ms:>8.2f} ms")
    print(f"  IndexedPQ:                    {ipq_pp_ms:>8.2f} ms")
    print(f"  Overhead of index:            {ipq_pp_ms - heap_pp_ms:>+8.2f} ms")

    print("\n" + "=" * 60)
    print("Conclusion:")
    print(f"  IndexedPQ is {speedup_update:.0f}x faster for priority updates.")
    print(f"  IndexedPQ is {speedup_remove:.0f}x faster for removals.")
    print(f"  Push/pop cost is roughly equal — the index adds minimal overhead")
    print(f"  for the common case. The benefit shows only when jobs need to be")
    print(f"  found by ID (starvation boost, cancellation).\n")


if __name__ == "__main__":
    run(n=10_000, updates=1_000, removals=500)
