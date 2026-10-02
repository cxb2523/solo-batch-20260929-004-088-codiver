"""
Runtime support for the traceable analysis pipeline.

This module holds two pieces of infrastructure used by the analyzer engine:

* :class:`ParseCache` - a bounded cache of successfully parsed Java ASTs.
* :class:`DetectionContext` - the trace collector passed to every
  detector so helper-level decisions can be recorded.

Cache placement decision
------------------------
The cache lives at the **parse layer**, not the detection layer. Parsing is
the expensive, pure step: ``source text -> AST``. Every enabled detector
then walks the same tree, so caching the AST once removes *all* repeated
parsing cost while keeping detector logic stateless and trivially
re-runnable. A detection-layer cache would (a) have to store one entry per
``(file, enabled-detector-set)`` combination, (b) duplicate the parsed AST
across those entries, and (c) still re-parse when the config toggles.

Only successful parses are cached: a failing source must be re-tried if it
changes, and caching the exception would hide edits.
"""

from __future__ import annotations

from collections import OrderedDict
from threading import RLock
from typing import Any, Dict, List, Optional


class ParseCache:
    """
    Bounded LRU cache of successfully parsed compilation units.

    Keys are source-code strings (the cache is content-addressed, which
    makes it safe when several paths hold identical content).
    """

    def __init__(self, max_entries: int = 64):
        self.max_entries = max_entries
        self._store: "OrderedDict[str, Any]" = OrderedDict()
        self.hits = 0
        self.misses = 0
        self._lock = RLock()

    def get(self, source: str) -> Optional[Any]:
        """Return the cached tree for ``source`` or ``None`` (and count it)."""
        with self._lock:
            tree = self._store.get(source)
            if tree is None:
                self.misses += 1
                return None
            self.hits += 1
            self._store.move_to_end(source)
            return tree

    def put(self, source: str, tree: Any) -> None:
        """Insert a freshly parsed tree, evicting the oldest entry if full."""
        with self._lock:
            self._store[source] = tree
            self._store.move_to_end(source)
            while len(self._store) > self.max_entries:
                self._store.popitem(last=False)

    def clear(self) -> None:
        """Drop all cached trees (counters are preserved for reporting)."""
        with self._lock:
            self._store.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)

    def stats(self) -> Dict[str, int]:
        """Return cache usage counters."""
        with self._lock:
            total = self.hits + self.misses
            return {
                "entries": len(self._store),
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate": round(self.hits / total, 4) if total else 0.0,
            }


class DetectionContext:
    """
    Per-file trace collector handed to every detector.

    Detectors record helper-level decisions with :meth:`helper_hit`.
    The engine records pipeline-level events directly into ``events``.
    Every event is a plain, JSON-serialisable dict so the whole chain can
    be replayed in the dashboard without keeping live AST objects.
    """

    def __init__(self, file_name: str, content_hash: str):
        self.file_name = file_name
        self.content_hash = content_hash
        self.events: List[Dict[str, Any]] = []
        self.helper_events: List[Dict[str, Any]] = []
        self._event_seq = 0

    def _next_seq(self) -> int:
        self._event_seq += 1
        return self._event_seq

    def stage(self, stage: str, status: str = "ok", **detail: Any) -> None:
        """Record a coarse-grained pipeline stage event."""
        self.events.append({
            "seq": self._next_seq(),
            "kind": "stage",
            "stage": stage,
            "status": status,
            "detail": detail,
        })

    def detector_started(self, detector: str, order: int,
                         category: str) -> None:
        """Record that a registered detector is about to run."""
        self.events.append({
            "seq": self._next_seq(),
            "kind": "detector_started",
            "detector": detector,
            "order": order,
            "category": category,
        })

    def detector_finished(self, detector: str, emitted: int,
                          raw: int, deduplicated: int) -> None:
        """Record detector completion with emission/dedup counters."""
        self.events.append({
            "seq": self._next_seq(),
            "kind": "detector_finished",
            "detector": detector,
            "emitted": emitted,
            "raw": raw,
            "deduplicated": deduplicated,
        })

    def detector_failed(self, detector: str, error: str) -> None:
        """Record a detector-level failure (the batch keeps running)."""
        self.events.append({
            "seq": self._next_seq(),
            "kind": "detector_failed",
            "detector": detector,
            "error": error,
        })

    def helper_hit(self, helper: str, target: str, result: Any,
                   detail: str = "", line: Optional[int] = None,
                   detector: str = "", rule_id: str = "",
                   severity: str = "", produced_finding: bool = True,
                   ) -> None:
        """
        Record one helper-level decision.

        When a helper verdict causes a finding, the event is linked to that
        finding's rule/target/line so the trace page can show which
        ``utils/helpers`` decision each finding came from.
        """
        self.helper_events.append({
            "seq": self._next_seq(),
            "kind": "helper_hit",
            "helper": helper,
            "detector": detector,
            "rule_id": rule_id,
            "severity": severity,
            "target": target,
            "line": line,
            "result": result,
            "detail": detail,
            "produced_finding": produced_finding,
        })

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the collected trace (ordered chronologically)."""
        return {
            "file_name": self.file_name,
            "content_hash": self.content_hash,
            "events": sorted(self.events, key=lambda item: item["seq"]),
            "helper_events": sorted(self.helper_events,
                                    key=lambda item: item["seq"]),
        }
