"""Both granularities must align; unique keys drive equal counts."""

from pathlib import Path

from analyzer_engine import analyze_paths
from traceability import (build_trace_views, group_by_file, group_by_rule,
                          severity_totals, pipeline_timeline)

SAMPLES = Path(__file__).resolve().parent / "sample_data"


def _sample_batch():
    return analyze_paths([
        str(SAMPLES / "broken_syntax.java"),
        str(SAMPLES / "god_class.java"),
        str(SAMPLES / "naming_violations.java"),
        str(SAMPLES / "clean.java"),
    ])


def test_two_granularity_totals_match_flat_count():
    batch = _sample_batch()
    views = build_trace_views(batch["findings"])
    assert views["aligned"] is True
    assert views["file_total"] == views["rule_total"] == views["total"]


def test_severity_breakdown_matches_both_views():
    batch = _sample_batch()
    views = build_trace_views(batch["findings"])
    file_sev = {level: sum(row[level] for row in views["by_file"])
                for level in ["Critical", "High", "Medium", "Low"]}
    assert file_sev == views["severity"]
    assert views["severity"]["Critical"] >= 1  # parse error counts once


def test_every_file_and_rule_aligned_entry_by_entry():
    batch = _sample_batch()
    findings = batch["findings"]
    by_file = group_by_file(findings)
    by_rule = group_by_rule(findings)

    # Each file-side row count equals direct findings for that file.
    for row in by_file:
        direct = sum(1 for f in findings if f["File"] == row["File"])
        assert row["Issues"] == direct
    # Each rule-side row count equals direct findings for that rule.
    for row in by_rule:
        direct = sum(1 for f in findings if f["RuleId"] == row["RuleId"])
        assert row["Issues"] == direct


def test_parse_error_counted_exactly_once_per_bad_file():
    batch = _sample_batch()
    parse_errors = [f for f in batch["findings"]
                    if f["RuleId"] == "parse-error"]
    assert len(parse_errors) == 1
    assert parse_errors[0]["File"] == "broken_syntax.java"


def test_same_file_multiple_rules_do_not_collide_keys():
    batch = _sample_batch()
    god_rules = {f["RuleId"] for f in batch["findings"]
                 if f["File"] == "god_class.java"}
    assert len(god_rules) > 1
    god_keys = [f["Key"] for f in batch["findings"]
                if f["File"] == "god_class.java"]
    assert len(god_keys) == len(set(god_keys))


def test_empty_input_is_aligned():
    views = build_trace_views([])
    assert views["aligned"] is True
    assert views["total"] == views["file_total"] == views["rule_total"] == 0


def test_pipeline_timeline_replays_layers_in_sequence():
    batch = _sample_batch()
    god = next(f for f in batch["files"] if f["file_name"] == "god_class.java")
    timeline = pipeline_timeline(god["trace"])
    layers = [row["Layer"] for row in timeline]
    assert layers[0] == "pipeline"
    assert "detector" in layers
    seqs = [row["seq"] for row in timeline]
    assert seqs == sorted(seqs)