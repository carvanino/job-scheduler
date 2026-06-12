"""
Indexed Priority Queue — alternative scheduling algorithm.

Extends the min-heap with a dictionary that maps job_id → heap position.
This makes three operations significantly faster:

  Operation          | MinHeap   | IndexedPQ
  -------------------|-----------|----------
  update_priority    | O(n)      | O(log n)   ← core starvation prevention op
  remove by id       | O(n)      | O(log n)   ← cancellation
  lookup position    | O(n)      | O(1)       ← index lookup

The index must be updated on every swap, which is the only extra cost.

Why it matters for this system:
  The starvation prevention loop runs every 30 seconds over all pending jobs.
  It calls update_priority() on every job that has waited too long.
  With a plain heap this is O(n) per update → O(n²) per starvation cycle.
  With the indexed PQ it is O(log n) per update → O(n log n) per cycle.
  At 500 pending jobs: 250,000 operations vs 4,500. That difference is why
  the index exists.
"""

from __future__ import annotations

from typing import Optional

from app.scheduler.heap import JobEntry


class IndexedPriorityQueue:
    """
    Min-heap with a job_id → heap position index.

    The _index dict is the only addition over MinHeap. Every swap must
    update both positions in _index — this is the critical invariant.
    If _index is ever out of sync with _heap positions, update_priority
    and remove will corrupt the heap silently.
    """

    def __init__(self) -> None:
        self._heap: list[JobEntry] = []
        self._index: dict[str, int] = {}   # job_id → heap array position

    # ── Public interface ─────────────────────────────────────────

    def push(self, entry: JobEntry) -> None:
        pos = len(self._heap)
        self._heap.append(entry)
        self._index[entry.job_id] = pos
        self._bubble_up(pos)

    def pop(self) -> Optional[JobEntry]:
        if not self._heap:
            return None
        if len(self._heap) == 1:
            top = self._heap.pop()
            del self._index[top.job_id]
            return top
        top = self._heap[0]
        last = self._heap.pop()
        del self._index[top.job_id]
        if self._heap:
            self._heap[0] = last
            self._index[last.job_id] = 0
            self._bubble_down(0)
        return top

    def peek(self) -> Optional[JobEntry]:
        return self._heap[0] if self._heap else None

    def update_priority(self, job_id: str, new_priority: float) -> bool:
        """
        Change a job's effective_priority and restore heap order.

        Step 1: O(1) lookup via index
        Step 2: mutate priority
        Step 3: O(log n) bubble_up  — if priority decreased (more urgent)
        Step 4: O(log n) bubble_down — if priority increased (less urgent)

        Total: O(log n)
        """
        if job_id not in self._index:
            return False
        pos = self._index[job_id]
        old = self._heap[pos].effective_priority
        self._heap[pos].effective_priority = new_priority
        if new_priority < old:
            self._bubble_up(pos)
        else:
            # pos may have changed after bubble_up — read from index again
            self._bubble_down(self._index[job_id])
        return True

    def remove(self, job_id: str) -> bool:
        """
        Remove any job by ID in O(log n).

        1. Find position via index — O(1)
        2. Replace with last element
        3. Fix heap order from that position — O(log n)
        """
        if job_id not in self._index:
            return False
        pos = self._index[job_id]
        del self._index[job_id]
        if pos == len(self._heap) - 1:
            self._heap.pop()
            return True
        # Move last element into the vacated position
        last = self._heap.pop()
        self._heap[pos] = last
        self._index[last.job_id] = pos
        # Restore heap: try both directions — only one will do anything
        self._bubble_up(pos)
        self._bubble_down(self._index[last.job_id])
        return True

    def __len__(self) -> int:
        return len(self._heap)

    def __contains__(self, job_id: str) -> bool:
        return job_id in self._index

    # ── Internal helpers ─────────────────────────────────────────

    def _swap(self, i: int, j: int) -> None:
        """
        Swap two elements and keep the index consistent.
        This is the only place swaps happen — index integrity depends on it.
        """
        self._heap[i], self._heap[j] = self._heap[j], self._heap[i]
        self._index[self._heap[i].job_id] = i
        self._index[self._heap[j].job_id] = j

    def _bubble_up(self, i: int) -> None:
        while i > 0:
            parent = (i - 1) // 2
            if self._heap[i] < self._heap[parent]:
                self._swap(i, parent)
                i = parent
            else:
                break

    def _bubble_down(self, i: int) -> None:
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
                self._swap(i, smallest)
                i = smallest
            else:
                break
