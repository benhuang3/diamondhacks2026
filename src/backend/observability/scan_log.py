"""In-memory per-scan step log.

Captures the browser-use agent's reasoning chain (evaluation / memory /
next goal / actions) so the frontend + extension can show progress while
the scan is running. Bounded ring per scan; oldest entries drop first.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict, deque
from typing import Deque

# Competitor jobs fan out to multiple concurrent browser-use agents plus
# discovery/synthesis stage markers, so per-scan capacity needs headroom.
_MAX_ENTRIES_PER_SCAN = 100
_MAX_SCANS_RETAINED = 200

_lock = threading.Lock()
# Insertion-ordered so we can LRU-evict the oldest scan when we hit the cap.
_log: "OrderedDict[str, Deque[dict]]" = OrderedDict()


def append(scan_id: str, entry: dict) -> None:
    """Append one step to the scan's log. Safe to call from any thread."""
    if not scan_id:
        return
    entry = {**entry, "ts": time.time()}
    with _lock:
        bucket = _log.get(scan_id)
        if bucket is None:
            bucket = deque(maxlen=_MAX_ENTRIES_PER_SCAN)
            _log[scan_id] = bucket
            # Evict oldest scans once we exceed the retention cap.
            while len(_log) > _MAX_SCANS_RETAINED:
                _log.popitem(last=False)
        else:
            _log.move_to_end(scan_id)
        bucket.append(entry)


def snapshot(scan_id: str) -> list[dict]:
    """Return a copy of the scan's step log in insertion order."""
    with _lock:
        bucket = _log.get(scan_id)
        if bucket is None:
            return []
        return list(bucket)


def clear(scan_id: str) -> None:
    with _lock:
        _log.pop(scan_id, None)
