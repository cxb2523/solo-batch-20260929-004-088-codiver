"""End-to-end pipeline: read -> parse -> dispatch -> helper -> aggregate."""

from pathlib import Path

from analyzer_engine import (analyze_source, analyze_paths, finding_key,
                             parse_java, PARSE_CACHE, StaticAnalyzerEngine)
from runtime import ParseCache

SAMPLES = Path(__file__).resolve().parent / "sample_data"
GOD = (SAMPLES / "god_class.java").read_text(encoding="utf-8")
BROKEN = (SAMPLES / "broken_syntax.java").read_text(encoding="utf-8")
NAMING = (SAMPLES / "naming_violations.java").read_text(encoding="utf-8")


def test_trace_covers_every_pipeline_layer():
    result = analyze_source(NAMING, "naming_violations.java")
    layers = {event["kind"] for event in result["trace"]["events"]}
    assert {"stage", "detector_started", "detector_finished"} <= layers

    stages = [e["stage"] for e in result["trace"]["events"]
              if e["kind"] == "stage"]
    assert stages[0] == "read"
    assert "parse" in stages
    assert "aggregate" in stages
    assert stages[-1] == "done"


def test_all_three_detector_families_run_in_order():
    result = analyze_source(GOD, "god_class.java")
    started = [e["detector"] for e in result["trace"]["events"]
               if e["kind"] == "detector_started"]
    assert started == ["design", "implementation", "naming", "documentation"]


def test_helper_decisions_are_traced():
    result = analyze_source(NAMING, "n.java")
    helpers = {e["helper"] for e in result["trace"]["helper_events"]}
    assert "utils.helpers.validate_class_name" in helpers
    assert "utils.helpers.validate_method_name" in helpers
    bad_class = next(e for e in result["trace"]["helper_events"]
                     if e["helper"].endswith("validate_class_name"))
    assert bad_class["result"] is False
    assert bad_class["line"] == 1


def test_every_finding_has_stable_unique_key_and_provenance():
    result = analyze_source(GOD, "god_class.java")
    keys = [f["Key"] for f in result["findings"]]
    assert len(keys) == len(set(keys))
    for finding in result["findings"]:
        assert {"File", "Detector", "RuleId", "Severity", "Line",
                "Type", "Target"} <= set(finding)
        assert finding["File"] == "god_class.java"
        assert finding["Key"] == finding_key(
            "god_class.java", finding, finding["Detector"])


def test_key_changes_with_file_rule_target_or_line():
    base_issue = {"Type": "God Class", "Target": "A", "Line": 5}
    k1 = finding_key("A.java", base_issue, "design")
    k2 = finding_key("B.java", base_issue, "design")
    k3 = finding_key("A.java", {**base_issue, "Type": "Lazy Class"}, "design")
    k4 = finding_key("A.java", {**base_issue, "Line": 9}, "design")
    assert len({k1, k2, k3, k4}) == 4


def test_repeated_runs_and_registry_reorder_keep_keys_stable():
    import detectors.base as reg
    first = analyze_source(GOD, "god_class.java")
    second = analyze_source(GOD, "god_class.java")
    assert [f["Key"] for f in first["findings"]] == \
           [f["Key"] for f in second["findings"]]

    original = list(reg.REGISTRY)
    try:
        reg.REGISTRY.sort(key=lambda item: -item["order"])
        reordered = analyze_source(GOD, "god_class.java")
    finally:
        reg.REGISTRY[:] = original
        reg.REGISTRY.sort(key=lambda item: (item["order"], item["name"]))

    assert sorted(f["Key"] for f in first["findings"]) == \
           sorted(f["Key"] for f in reordered["findings"])


def test_legacy_run_still_returns_issues_and_tree():
    engine = StaticAnalyzerEngine(GOD, cache=ParseCache())
    issues, tree = engine.run()
    assert isinstance(issues, list) and issues
    assert tree is not None


def test_parse_failure_degrades_to_one_error_entry():
    result = analyze_source(BROKEN, "broken_syntax.java")
    assert result["status"] == "error"
    assert len(result["findings"]) == 1
    finding = result["findings"][0]
    assert finding["Type"] == "Parse Error"
    assert finding["Severity"] == "Critical"
    assert finding["Category"] == "ParseError"
    # metrics still well-formed, counts stay honest
    assert result["metrics"]["total_classes"] == 0
    assert "parse" in [e["stage"] for e in result["trace"]["events"]
                       if e.get("status") == "error"]


def test_batch_continues_after_one_bad_file():
    result = analyze_paths([
        str(SAMPLES / "broken_syntax.java"),
        str(SAMPLES / "god_class.java"),
        str(SAMPLES / "naming_violations.java"),
    ])
    statuses = {f["file_name"]: f["status"] for f in result["files"]}
    assert statuses["broken_syntax.java"] == "error"
    assert statuses["god_class.java"] == "ok"
    keys = [f["Key"] for f in result["findings"]]
    assert len(keys) == len(set(keys))


def test_missing_file_degrades_to_read_error():
    result = analyze_paths([str(SAMPLES / "does_not_exist.java")])
    assert result["files"][0]["status"] == "read-error"
    assert result["files"][0]["findings"][0]["Type"] == "Read Error"


def test_parse_cache_returns_hit_on_identical_source():
    cache = ParseCache()
    tree1, hit1 = parse_java(GOD, cache)
    tree2, hit2 = parse_java(GOD, cache)
    assert hit1 is False and hit2 is True
    assert tree1 is tree2
    assert cache.stats()["hits"] == 1


def test_failed_parse_is_not_cached():
    cache = ParseCache()
    for _ in range(2):
        try:
            parse_java(BROKEN, cache)
        except ValueError:
            pass
    assert cache.stats()["hits"] == 0
    assert len(cache) == 0


def test_lru_cache_evicts_oldest_entry():
    cache = ParseCache(max_entries=2)
    parse_java("class A {}", cache)
    parse_java("class B {}", cache)
    parse_java("class C {}", cache)  # evicts A
    _, hit_c = parse_java("class C {}", cache)
    _, hit_a = parse_java("class A {}", cache)
    assert hit_c is True and hit_a is False


def test_config_disables_detector_family():
    full = analyze_source(GOD, "g.java")
    design_only = analyze_source(GOD, "g.java",
                                 {"design": True, "implementation": False,
                                  "naming": False, "documentation": False})
    assert {f["Detector"] for f in design_only["findings"]} == {"design"}
    assert len(design_only["findings"]) < len(full["findings"])