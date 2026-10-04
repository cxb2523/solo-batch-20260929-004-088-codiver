"""
Traceability / Replay Support
Records every step of the analysis pipeline (read -> parse -> dispatch ->
detect -> helper decisions -> aggregation) so the whole chain can be
replayed in the dashboard traceability page, and provides the dedup /
aggregation logic that keeps per-file and per-rule/severity counts aligned.
"""

import contextvars
from contextlib import contextmanager
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Tuple


# Pipeline step identifiers, in execution order.
STEP_READ = "read"
STEP_PARSE = "parse"
STEP_DISPATCH = "dispatch"
STEP_DETECT = "detect"
STEP_HELPER = "helper"
STEP_AGGREGATE = "aggregate"
STEP_ERROR = "error"

PIPELINE_STEPS = (
    STEP_READ,
    STEP_PARSE,
    STEP_DISPATCH,
    STEP_DETECT,
    STEP_HELPER,
    STEP_AGGREGATE,
)


@dataclass
class TraceEvent:
    """A single recorded step of the analysis pipeline."""
    seq: int
    step: str
    file: str
    detail: str
    items: int = 0
    cached: bool = False
    elapsed_ms: float = 0.0


class TraceRecorder:
    """Collects TraceEvents in pipeline execution order."""

    def __init__(self) -> None:
        self.events: List[TraceEvent] = []
        self._seq = 0

    def record(self, step: str, file: str, detail: str, items: int = 0,
               cached: bool = False, elapsed_ms: float = 0.0) -> TraceEvent:
        """Append one event to the trace."""
        self._seq += 1
        event = TraceEvent(
            seq=self._seq,
            step=step,
            file=file,
            detail=detail,
            items=items,
            cached=cached,
            elapsed_ms=round(elapsed_ms, 3),
        )
        self.events.append(event)
        return event

    def steps_for(self, file: str) -> List[str]:
        """Return the ordered step names recorded for one file."""
        return [e.step for e in self.events if e.file == file]

    def to_rows(self) -> List[Dict[str, Any]]:
        """Export events as a list of plain dicts (DataFrame-ready)."""
        return [asdict(e) for e in self.events]


# Active (recorder, file) pair, used so deeply nested helpers
# (utils/helpers.py) can emit decisions without threading a recorder
# through every call signature.
_active_context: contextvars.ContextVar = contextvars.ContextVar(
    "trace_active_context", default=None
)


@contextmanager
def trace_context(recorder: TraceRecorder, file_name: str):
    """Bind a recorder + file name as the active trace context."""
    token = _active_context.set((recorder, file_name))
    try:
        yield
    finally:
        _active_context.reset(token)


def emit_helper(detail: str) -> None:
    """
    Emit a helper-decision trace event if a trace context is active.
    No-op during normal (untraced) analysis.
    """
    ctx = _active_context.get()
    if ctx is not None:
        recorder, file_name = ctx
        recorder.record(STEP_HELPER, file_name, detail)


def issue_key(issue: Dict[str, Any]) -> Tuple[str, str, str, str, str]:
    """
    Unique identity of a finding.

    Decision: the key is the full content identity
    (File, Category, Type, Target, Reason). A file hit by several rules
    yields one entry per (rule, target) pair, so multi-rule files are
    never collapsed; identical findings reported twice for the same
    target with the same reason describe the same problem and are
    counted once. Because both granularities (by file, by rule/severity)
    are groupings of the same deduplicated list, their totals always
    match item by item.
    """
    return (
        str(issue.get("File", "")),
        str(issue.get("Category", "")),
        str(issue.get("Type", "")),
        str(issue.get("Target", "")),
        str(issue.get("Reason", "")),
    )


def dedup_issues(issues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Deduplicate issues by issue_key, keeping first-occurrence order.
    """
    seen = set()
    unique = []
    for issue in issues:
        key = issue_key(issue)
        if key not in seen:
            seen.add(key)
            unique.append(issue)
    return unique


def make_error_entry(file_name: str, message: str) -> Dict[str, Any]:
    """
    Degraded entry for a file that failed to parse.

    Decision: a parse failure is degraded into exactly one error entry
    instead of skipping the file. The batch keeps running, the file
    stays visible in the by-file view, and because the entry flows
    through the same dedup/aggregation path, both granularities count
    it identically (no count distortion).
    """
    return {
        "File": file_name,
        "Type": "Parse Error",
        "Target": file_name,
        "Severity": "Error",
        "Reason": message,
        "Category": "Parse",
    }


class BatchReport:
    """
    Result of analyzing a batch of files: deduplicated issues, per-file
    metrics, parse errors and the full pipeline trace.
    """

    def __init__(self, recorder: Optional[TraceRecorder] = None) -> None:
        self.recorder = recorder or TraceRecorder()
        self.issues: List[Dict[str, Any]] = []
        self.metrics: Dict[str, Dict[str, Any]] = {}
        self.errors: Dict[str, str] = {}

    def by_file(self) -> Dict[str, int]:
        """Issue counts grouped by file."""
        counts: Dict[str, int] = {}
        for issue in self.issues:
            key = str(issue.get("File", ""))
            counts[key] = counts.get(key, 0) + 1
        return counts

    def by_rule_severity(self) -> Dict[Tuple[str, str], int]:
        """Issue counts grouped by (rule type, severity)."""
        counts: Dict[Tuple[str, str], int] = {}
        for issue in self.issues:
            key = (str(issue.get("Type", "")), str(issue.get("Severity", "")))
            counts[key] = counts.get(key, 0) + 1
        return counts

    def counts_aligned(self) -> bool:
        """
        True when both granularities account for exactly the same items:
        sum(by_file) == sum(by_rule_severity) == total unique issues.
        """
        total = len(self.issues)
        return (
            sum(self.by_file().values()) == total
            and sum(self.by_rule_severity().values()) == total
        )

    def trace_rows(self) -> List[Dict[str, Any]]:
        """Full pipeline trace as DataFrame-ready rows."""
        return self.recorder.to_rows()
