"""Self-check: run the traced batch analysis over the repo sample data
(tests/sample_data/java/*.java) and verify the traceability page data:
both granularities must align item by item, and the full pipeline trace
must exist for every file.

Usage: python scripts/selfcheck_traceability.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "java_analyzer"))

from analyzer_engine import analyze_batch, parse_cache_stats  # noqa: E402


def main() -> int:
    sample_dir = ROOT / "tests" / "sample_data" / "java"
    files = {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(sample_dir.glob("*.java"))
    }
    if not files:
        print("No sample .java files found.")
        return 1

    # Run twice to also exercise the parse-layer cache.
    analyze_batch(files)
    report = analyze_batch(files)

    print("== By File ==")
    for name, count in report.by_file().items():
        print(f"  {name:20s} {count}")
    print("== By Rule & Severity ==")
    for (rule, severity), count in sorted(report.by_rule_severity().items()):
        print(f"  {rule:30s} {severity:8s} {count}")

    total = len(report.issues)
    by_file_sum = sum(report.by_file().values())
    by_rule_sum = sum(report.by_rule_severity().values())
    print(f"\nTotals: by_file={by_file_sum} by_rule_severity={by_rule_sum} "
          f"unique={total}")
    print(f"Parse cache: {parse_cache_stats['hits']} hits / "
          f"{parse_cache_stats['misses']} misses")
    print(f"Parse errors degraded: {list(report.errors) or 'none'}")
    print(f"Trace events recorded: {len(report.recorder.events)}")

    if not report.counts_aligned():
        print("FAIL: granularity counts are misaligned.")
        return 1
    traced = {e.file for e in report.recorder.events}
    missing = set(files) - traced
    if missing:
        print(f"FAIL: no trace for {missing}")
        return 1
    print("OK: counts aligned across both granularities; trace complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
