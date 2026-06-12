"""
Min-heap based priority queue.

Jobs are ordered by three keys in sequence:
  1. effective_priority  — lower number = higher urgency (1=High beats 3=Low)
  2. scheduled_at        — earlier time runs first
  3. created_at          — earlier creation runs first (FIFO tiebreak)

This is the primary scheduling algorithm required by the task.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


def _sentinel_dt() -> datetime:
    """Far-future datetime used when scheduled_at is None."""
    return datetime(9999, 12, 31, tzinfo=timezone.utc)


@dataclass(order=False)
class JobEntry:
    job_id: str
    effective_priority: float      # lower = more urgent
    scheduled_at: datetime
    created_at: datetime
    job_type: str = ""

    def __lt__(self, other: "JobEntry") -> bool:
        """Comparison used by the heap to determine ordering."""
        if self.effective_priority != other.effective_priority:
            return self.effective_priority < other.effective_priority
        if self.scheduled_at != other.scheduled_at:
            return self.scheduled_at < other.scheduled_at
        return self.created_at < other.created_at


class MinHeap:
    """
    Binary min-heap.

    Internal layout: the heap is stored as a flat list. For any element at
    index i:
      - parent    : (i - 1) // 2
      - left child: 2 * i + 1
      - right child: 2 * i + 2

    Push: append to end, bubble_up to restore order — O(log n)
    Pop:  swap root with last element, remove last, bubble_down — O(log n)
    Peek: read index 0 without removing — O(1)
    """

    def __init__(self) -> None:
        self._heap: list[JobEntry] = []

    # ── Public interface ─────────────────────────────────────────

    def push(self, entry: JobEntry) -> None:
        self._heap.append(entry)
        self._bubble_up(len(self._heap) - 1)

    def pop(self) -> Optional[JobEntry]:
        if not self._heap:
            return None
        if len(self._heap) == 1:
            return self._heap.pop()
        top = self._heap[0]
        self._heap[0] = self._heap.pop()   # move last element to root
        self._bubble_down(0)
        return top

    def peek(self) -> Optional[JobEntry]:
        return self._heap[0] if self._heap else None

    def remove_by_id(self, job_id: str) -> bool:
        """
        Linear scan to find and remove a job. O(n) — use IndexedPQ for O(log n).
        Kept here for completeness; cancellation uses IndexedPQ in production.
        """
        for i, entry in enumerate(self._heap):
            if entry.job_id == job_id:
                self._heap[i] = self._heap[-1]
                self._heap.pop()
                if i < len(self._heap):
                    self._bubble_up(i)
                    self._bubble_down(i)
                return True
        return False

    def __len__(self) -> int:
        return len(self._heap)

    def __contains__(self, job_id: str) -> bool:
        return any(e.job_id == job_id for e in self._heap)

    # ── Internal helpers ─────────────────────────────────────────

    def _bubble_up(self, i: int) -> None:
        """
        Restore heap property upward from index i.
        If the element at i is smaller than its parent, swap them and continue.
        """
        while i > 0:
            parent = (i - 1) // 2
            if self._heap[i] < self._heap[parent]:
                self._heap[i], self._heap[parent] = self._heap[parent], self._heap[i]
                i = parent
            else:
                break

    def _bubble_down(self, i: int) -> None:
        """
        Restore heap property downward from index i.
        Find the smallest of the element and its children, swap if needed.
        """
        n = len(self._heap)
        while True:
            smallest = i
            left = 2 * i + 1
            right = 2 * i + 2
            if left < n and self._heap[left] < self._heap[smallest]:
                smallest = left
            if right < n and self._heap[right] < self._heap[smallest]:
                smallest = right
            if smallest != i:
                self._heap[i], self._heap[smallest] = self._heap[smallest], self._heap[i]
                i = smallest
            else:
                break
