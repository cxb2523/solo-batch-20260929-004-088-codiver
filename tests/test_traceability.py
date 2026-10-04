"""
Tests for the traceable analysis pipeline:
registry ordering, dedup keys, parse-failure degradation, parse caching,
helper-decision tracing and cross-granularity count alignment.
"""

from collections import Counter
from pathlib import Path

import pytest

import detectors.base as base
from analyzer_engine import (
    StaticAnalyzerEngine,
    analyze_batch,
    parse_cache_stats,
    parse_java,
    reset_parse_cache,
)
from traceability import (
    STEP_AGGREGATE,
    STEP_DETECT,
    STEP_DISPATCH,
    STEP_HELPER,
    STEP_PARSE,
    STEP_READ,
    dedup_issues,
    issue_key,
)

SAMPLE_DIR = Path(__file__).parent / "sample_data" / "java"

VALID_CODE = (SAMPLE_DIR / "OrderService.java").read_text(encoding="utf-8")
BROKEN_CODE = (SAMPLE_DIR / "Broken.java").read_text(encoding="utf-8")
CLEAN_CODE = (SAMPLE_DIR / "Clean.java").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def clear_parse_cache():
    reset_parse_cache()
    yield
    reset_parse_cache()


# ---------------------------------------------------------------- registry

def test_registry_is_centralized_and_ordered():
    keys = [key for key, _ in base.DETECTOR_REGISTRY]
    assert keys == ["design", "implementation", "naming", "documentation"]


def test_duplicate_registration_rejected():
    with pytest.raises(ValueError):
        base.register_detector("design", base.DETECTOR_REGISTRY[0][1])


def test_build_detectors_respects_config_and_order():
    detectors = base.build_detectors({"design": False, "naming": True})
    names = [type(d).__name__ for d in detectors]
    assert names == ["ImplementationSmells", "NamingSmells", "DocumentationSmells"]


def test_registration_order_changes_sequence_but_not_dedup_results():
    report_normal = analyze_batch({"OrderService.java": VALID_CODE})

    original = list(base.DETECTOR_REGISTRY)
    try:
        base.DETECTOR_REGISTRY[:] = list(reversed(original))
        report_reversed = analyze_batch({"OrderService.java": VALID_CODE})
    finally:
        base.DETECTOR_REGISTRY[:] = original

    # Same unique findings, same counts in both granularities.
    assert Counter(issue_key(i) for i in report_normal.issues) == \
           Counter(issue_key(i) for i in report_reversed.issues)
    assert report_normal.by_file() == report_reversed.by_file()
    assert report_normal.by_rule_severity() == report_reversed.by_rule_severity()


# ------------------------------------------------------------------ dedup

def test_issue_key_dedup_collapses_exact_duplicates_only():
    issues = [
        {"File": "A.java", "Type": "God Class", "Target": "Foo",
         "Severity": "Critical", "Reason": "r", "Category": "Design"},
        {"File": "A.java", "Type": "God Class", "Target": "Foo",
         "Severity": "Critical", "Reason": "r", "Category": "Design"},
        # Same file, different rule -> must NOT be collapsed.
        {"File": "A.java", "Type": "Data Class", "Target": "Foo",
         "Severity": "Low", "Reason": "r2", "Category": "Design"},
        # Same rule, different file -> must NOT be collapsed.
        {"File": "B.java", "Type": "God Class", "Target": "Foo",
         "Severity": "Critical", "Reason": "r", "Category": "Design"},
    ]
    unique = dedup_issues(issues)
    assert len(unique) == 3
    assert [issue_key(i) for i in unique] == [
        issue_key(issues[0]), issue_key(issues[2]), issue_key(issues[3])
    ]


def test_both_granularities_align_on_multi_rule_file():
    report = analyze_batch({"OrderService.java": VALID_CODE})
    assert report.counts_aligned()
    assert sum(report.by_file().values()) == len(report.issues)
    assert sum(report.by_rule_severity().values()) == len(report.issues)
    # The sample file is hit by several distinct rules.
    assert len(report.by_rule_severity()) > 1


# ------------------------------------------------------- parse failure

def test_parse_failure_degrades_to_single_error_entry():
    report = analyze_batch({
        "OrderService.java": VALID_CODE,
        "Broken.java": BROKEN_CODE,
    })
    # Batch did not abort: the good file still produced findings.
    assert "Broken.java" in report.errors
    assert "OrderService.java" in report.by_file()

    broken_entries = [i for i in report.issues if i["File"] == "Broken.java"]
    assert len(broken_entries) == 1
    entry = broken_entries[0]
    assert entry["Type"] == "Parse Error"
    assert entry["Severity"] == "Error"
    assert entry["Category"] == "Parse"

    # Error entry flows through the same aggregation -> counts stay aligned.
    assert report.counts_aligned()
    assert report.by_file()["Broken.java"] == 1
    assert report.by_rule_severity()[("Parse Error", "Error")] == 1


def test_engine_run_still_raises_valueerror_on_bad_syntax():
    engine = StaticAnalyzerEngine(BROKEN_CODE)
    with pytest.raises(ValueError):
        engine.run()


# ------------------------------------------------------------ parse cache

def test_parse_cache_hit_returns_identical_results():
    tree1, hit1 = parse_java(VALID_CODE)
    tree2, hit2 = parse_java(VALID_CODE)
    assert hit1 is False
    assert hit2 is True
    assert tree1 is tree2
    assert parse_cache_stats["hits"] == 1
    assert parse_cache_stats["misses"] == 1


def test_cached_reanalysis_produces_identical_issues():
    report1 = analyze_batch({"OrderService.java": VALID_CODE})
    report2 = analyze_batch({"OrderService.java": VALID_CODE})
    assert report1.issues == report2.issues
    assert parse_cache_stats["hits"] == 1
    # Second run's parse event is marked as a cache hit.
    parse_events = [e for e in report2.recorder.events if e.step == STEP_PARSE]
    assert parse_events and parse_events[0].cached is True


def test_failed_parses_are_not_cached():
    for _ in range(2):
        report = analyze_batch({"Broken.java": BROKEN_CODE})
        assert "Broken.java" in report.errors
    assert parse_cache_stats["hits"] == 0
    assert parse_cache_stats["misses"] == 2


# --------------------------------------------------------- trace coverage

def test_trace_covers_full_pipeline_for_one_file():
    report = analyze_batch({"OrderService.java": VALID_CODE})
    steps = report.recorder.steps_for("OrderService.java")
    assert steps[0] == STEP_READ
    assert STEP_PARSE in steps
    assert steps.count(STEP_DISPATCH) == 4  # all four detectors dispatched
    assert steps.count(STEP_DETECT) == 4    # all four detectors reported hits
    assert STEP_HELPER in steps             # naming helpers emitted decisions
    batch_steps = report.recorder.steps_for("<batch>")
    assert batch_steps == [STEP_AGGREGATE]


def test_helper_decisions_are_traced():
    report = analyze_batch({"OrderService.java": VALID_CODE})
    helper_details = [
        e.detail for e in report.recorder.events if e.step == STEP_HELPER
    ]
    assert any("validate_class_name('orderService') -> False" in d
               for d in helper_details)
    assert any("validate_method_name('CalculateTotal') -> False" in d
               for d in helper_details)


def test_trace_marks_parse_error_step():
    report = analyze_batch({"Broken.java": BROKEN_CODE})
    error_events = [e for e in report.recorder.events if e.step == "error"]
    assert len(error_events) == 1
    assert error_events[0].file == "Broken.java"


# ------------------------------------------------------- sample selfcheck

def test_repo_sample_data_batch_selfcheck():
    files = {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(SAMPLE_DIR.glob("*.java"))
    }
    assert {"OrderService.java", "Broken.java", "Clean.java"} <= set(files)

    report = analyze_batch(files)

    # Every file accounted for in the by-file view.
    assert set(report.by_file()) == set(files)
    # Broken file degraded, others analyzed.
    assert set(report.errors) == {"Broken.java"}
    assert "OrderService.java" in report.metrics
    # Counts align across both granularities, item by item.
    assert report.counts_aligned()
    # Trace replay exists for every file plus the batch aggregation.
    traced_files = {e.file for e in report.recorder.events}
    assert set(files) | {"<batch>"} <= traced_files


def test_config_disables_detectors_without_breaking_alignment():
    report = analyze_batch(
        {"OrderService.java": VALID_CODE},
        config={"design": False, "documentation": False},
    )
    categories = {i["Category"] for i in report.issues}
    assert "Design" not in categories
    assert "Documentation" not in categories
    assert report.counts_aligned()
