"""Minimal in-process counter registry with Prometheus text exposition.

Keeps the dependency surface small (no prometheus-client dep). Counters are
keyed by name + frozenset of label pairs so labels can be arbitrary. All
operations are O(1) and threadsafe via a single asyncio-friendly lock: we
only use a plain ``threading.Lock`` because increments are trivial.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from typing import Iterable


class _Counter:
    __slots__ = ("name", "help", "_values", "_lock")

    def __init__(self, name: str, help_text: str) -> None:
        self.name = name
        self.help = help_text
        self._values: dict[tuple[tuple[str, str], ...], float] = defaultdict(float)
        self._lock = threading.Lock()

    def inc(self, amount: float = 1.0, **labels: str) -> None:
        key = tuple(sorted(labels.items()))
        with self._lock:
            self._values[key] += amount

    def snapshot(self) -> list[tuple[tuple[tuple[str, str], ...], float]]:
        with self._lock:
            return list(self._values.items())


class MetricsRegistry:
    """Named counter registry. Lookups are by string name."""

    def __init__(self) -> None:
        self._counters: dict[str, _Counter] = {}
        self._lock = threading.Lock()

    def counter(self, name: str, help_text: str) -> _Counter:
        with self._lock:
            c = self._counters.get(name)
            if c is None:
                c = _Counter(name, help_text)
                self._counters[name] = c
            return c

    def inc(self, name: str, amount: float = 1.0, **labels: str) -> None:
        # Auto-register with a blank help string; callers that want rich
        # descriptions should call counter() during startup.
        self.counter(name, "").inc(amount, **labels)

    def render_prometheus(self) -> str:
        """Serialize all counters as Prometheus text exposition format."""
        lines: list[str] = []
        with self._lock:
            counters = list(self._counters.values())
        for c in counters:
            lines.append(f"# HELP {c.name} {c.help or c.name}")
            lines.append(f"# TYPE {c.name} counter")
            for label_pairs, value in c.snapshot():
                if label_pairs:
                    rendered = ",".join(
                        f'{k}="{_escape(v)}"' for k, v in label_pairs
                    )
                    lines.append(f"{c.name}{{{rendered}}} {value}")
                else:
                    lines.append(f"{c.name} {value}")
        return "\n".join(lines) + "\n"


def _escape(v: str) -> str:
    return v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


# Module-level singleton. Workers and middleware import this directly.
metrics = MetricsRegistry()


def _register_core_counters() -> None:
    metrics.counter("http_requests_total", "HTTP requests served, by route/method/status")
    metrics.counter("http_rate_limited_total", "Requests rejected by rate limiter")
    metrics.counter("scans_started_total", "Scan jobs started")
    metrics.counter("scans_completed_total", "Scan jobs that reached status=done")
    metrics.counter("scans_failed_total", "Scan jobs that reached status=failed")
    metrics.counter("competitor_jobs_started_total", "Competitor jobs started")
    metrics.counter("competitor_jobs_completed_total", "Competitor jobs that reached status=done")
    metrics.counter("competitor_jobs_failed_total", "Competitor jobs that reached status=failed")
    metrics.counter("claude_calls_total", "Calls attempted against the Anthropic API")
    metrics.counter("claude_call_failures_total", "Claude calls that raised and fell back to demo")
    metrics.counter("ssrf_rejections_total", "URL submissions rejected by the SSRF guard")


_register_core_counters()
