"""In-memory cancellation registry for background jobs.

Simple set keyed by job/scan id. Threadsafe. Workers poll ``is_cancelled``
at stage boundaries and exit cleanly; routes call ``mark_cancelled`` when
the user hits the stop button.

The registry is process-local — if you restart the server mid-job, the
DB still carries ``status="cancelled"`` (persisted by the route) so the
UI reflects the terminal state even without the in-memory flag.
"""

from __future__ import annotations

import threading

_cancelled: set[str] = set()
_lock = threading.Lock()


def mark_cancelled(job_id: str) -> None:
    if not job_id:
        return
    with _lock:
        _cancelled.add(job_id)


def is_cancelled(job_id: str) -> bool:
    if not job_id:
        return False
    with _lock:
        return job_id in _cancelled


def clear(job_id: str) -> None:
    with _lock:
        _cancelled.discard(job_id)


class CancelledByUser(Exception):
    """Raised by worker stage checks when the user has requested a stop."""

    def __init__(self, job_id: str) -> None:
        super().__init__(f"job {job_id} cancelled by user")
        self.job_id = job_id


def raise_if_cancelled(job_id: str) -> None:
    if is_cancelled(job_id):
        raise CancelledByUser(job_id)
