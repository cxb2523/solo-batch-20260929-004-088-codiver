"""
Trace aggregation for the provenance page.

The pipeline emits one finding dict per de-duplicated hit (see
``analyzer_engine.analyze_source``). This module turns that flat list into
the two granularities the trace page can switch between:

* ``by_file``  - one row per file;
* ``by_rule``  - one row per rule/severity (``RuleId``).

Both views are computed from the *same* de-duplicated finding list, and
:func:`build_trace_views` verifies that their per-row counts sum to the
same total. Because the unique key already collapsed duplicates, the two
granularities cannot disagree: summing the file column equals summing the
rule column equals the raw finding count.
"""

from __future__ import annotations

from typing import Any, Dict, List

from utils.helpers import severity_rank

SEVERITY_LEVELS = ["Critical", "High", "Medium", "Low"]


def _severity_buckets() -> Dict[str, int]:
    return {level: 0 for level in SEVERITY_LEVELS}


def group_by_file(findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Aggregate findings to one row per source file."""
    grouped: Dict[str, Dict[str, Any]] = {}
    for finding in findings:
        file_name = finding.get("File", "<unknown>")
        row = grouped.setdefault(file_name, {
            "File": file_name,
            "Issues": 0,
            "Rules": set(),
            "severity": _severity_buckets(),
        })
        row["Issues"] += 1
        row["Rules"].add(finding.get("RuleId", finding.get("Type", "?")))
        severity = finding.get("Severity", "Low")
        if severity in row["severity"]:
            row["severity"][severity] += 1

    rows = []
    for row in grouped.values():
        rows.append({
            "File": row["File"],
            "Issues": row["Issues"],
            "Critical": row["severity"]["Critical"],
            "High": row["severity"]["High"],
            "Medium": row["severity"]["Medium"],
            "Low": row["severity"]["Low"],
            "Distinct Rules": len(row["Rules"]),
        })
    rows.sort(key=lambda item: (-item["Issues"], item["File"]))
    return rows


def group_by_rule(findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Aggregate findings to one row per rule/severity."""
    grouped: Dict[str, Dict[str, Any]] = {}
    for finding in findings:
        rule_id = finding.get("RuleId", finding.get("Type", "?"))
        row = grouped.setdefault(rule_id, {
            "RuleId": rule_id,
            "Type": finding.get("Type", "Unknown"),
            "Detector": finding.get("Detector", ""),
            "Category": finding.get("Category", ""),
            "Severity": finding.get("Severity", "Low"),
            "Files": set(),
            "Issues": 0,
        })
        row["Issues"] += 1
        row["Files"].add(finding.get("File", "<unknown>"))

    rows = []
    for row in grouped.values():
        rows.append({
            "RuleId": row["RuleId"],
            "Type": row["Type"],
            "Detector": row["Detector"],
            "Category": row["Category"],
            "Severity": row["Severity"],
            "Issues": row["Issues"],
            "Files Hit": len(row["Files"]),
        })
    rows.sort(key=lambda item: (severity_rank(item["Severity"]),
                                item["Detector"], item["Type"]))
    return rows


def severity_totals(findings: List[Dict[str, Any]]) -> Dict[str, int]:
    """Count findings at each severity level."""
    totals = _severity_buckets()
    for finding in findings:
        severity = finding.get("Severity", "Low")
        if severity in totals:
            totals[severity] += 1
    return totals


def build_trace_views(findings: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Build both granularity views plus alignment metadata.

    Returns a dict with the flat findings, ``by_file`` rows, ``by_rule``
    rows, severity totals and an ``aligned`` flag. ``aligned`` is True only
    when the file-side and rule-side totals match each other and the flat
    finding count (and their severity breakdowns match too).
    """
    by_file = group_by_file(findings)
    by_rule = group_by_rule(findings)
    totals = severity_totals(findings)

    file_total = sum(row["Issues"] for row in by_file)
    rule_total = sum(row["Issues"] for row in by_rule)
    file_sev = {level: sum(row[level] for row in by_file)
                for level in SEVERITY_LEVELS}

    aligned = (
        file_total == rule_total == len(findings)
        and file_sev == totals
    )
    return {
        "total": len(findings),
        "by_file": by_file,
        "by_rule": by_rule,
        "severity": totals,
        "file_total": file_total,
        "rule_total": rule_total,
        "aligned": aligned,
    }


def pipeline_timeline(trace: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Flatten a per-file trace into replayable stage rows.

    Includes pipeline stages, detector dispatch and helper-level decisions,
    ordered by the event sequence number assigned during collection.
    """
    rows = []
    for event in trace.get("events", []):
        if event.get("kind") == "stage":
            rows.append({
                "seq": event["seq"],
                "Layer": "pipeline",
                "Step": event["stage"],
                "Status": event.get("status", "ok"),
                "Detail": _summarise(event.get("detail", {})),
            })
        elif event.get("kind") == "detector_started":
            rows.append({
                "seq": event["seq"],
                "Layer": "detector",
                "Step": "run:{}".format(event.get("detector", "")),
                "Status": "started",
                "Detail": "order={} category={}".format(
                    event.get("order"), event.get("category")),
            })
        elif event.get("kind") == "detector_finished":
            rows.append({
                "seq": event["seq"],
                "Layer": "detector",
                "Step": "done:{}".format(event.get("detector", "")),
                "Status": "ok",
                "Detail": ("raw={raw} unique={uniq}".format(
                    raw=event.get("raw", 0),
                    uniq=event.get("deduplicated", 0))),
            })
        elif event.get("kind") == "detector_failed":
            rows.append({
                "seq": event["seq"],
                "Layer": "detector",
                "Step": "failed:{}".format(event.get("detector", "")),
                "Status": "error",
                "Detail": event.get("error", ""),
            })
    for event in trace.get("helper_events", []):
        rows.append({
            "seq": event["seq"],
            "Layer": "helper",
            "Step": event.get("helper", ""),
            "Status": "finding" if event.get("produced_finding") else "checked",
            "Detail": "{target} L{line} -> {detail}".format(
                target=event.get("target", ""),
                line=event.get("line") or "-",
                detail=event.get("detail", "")),
        })
    rows.sort(key=lambda item: item["seq"])
    return rows


def _summarise(detail: Dict[str, Any]) -> str:
    if not detail:
        return ""
    return ", ".join("{}={}".format(key, value)
                     for key, value in detail.items())