# Analysis Traceability & Pipeline Decisions

The Java analysis chain is fully replayable: every step from file read,
AST parse, detector dispatch (`detectors/base.py` registry), the
design / implementation / naming-docs detectors, helper decisions in
`utils/helpers.py`, down to final aggregation emits a `TraceEvent`
(`src/java_analyzer/traceability.py`). The dashboard traceability page
(`render_traceability_page` in `src/java_analyzer/utils/ui_components.py`)
renders the replay plus two switchable granularities — by file and by
rule/severity — whose counts are aligned item by item.

## Decision 1: Centralized registry, not decorator auto-discovery

Detectors are registered in one explicit, ordered list
(`DETECTOR_REGISTRY` in `detectors/base.py`, populated at import time by
`analyzer_engine.py`). Decorator-based auto-discovery was rejected: it
couples execution order to module import order, which is invisible in
code review and breaks when imports are rearranged.

Registration order **does** change the sequence of raw issues (detectors
run sequentially and append results in order), but it **does not** change
deduplication results or any count: dedup keys are content-based, so the
set of unique findings and both granularity totals are order-invariant.
Covered by `test_registration_order_changes_sequence_but_not_dedup_results`.

## Decision 2: Unique key = (File, Category, Type, Target, Reason)

`traceability.issue_key` uses the full content identity of a finding. A
file hit by several rules yields one entry per (rule, target, reason)
triple, so multi-rule files are never collapsed; byte-identical findings
reported twice for the same target describe the same problem and are
counted once. Both granularities are groupings of the same deduplicated
list, so `sum(by_file) == sum(by_rule_severity) == total` always holds
(`BatchReport.counts_aligned`, asserted in the UI banner and in tests).

## Decision 3: Parse failure degrades to one error entry

A file that fails to parse is **not** skipped and does **not** abort the
batch. `analyze_batch` catches the `ValueError`, records an `error` trace
event, and substitutes exactly one degraded entry
(`Type=Parse Error, Severity=Error, Category=Parse`). The file stays
visible in the by-file view, and because the entry flows through the same
dedup/aggregation path, both granularities count it identically — no
count distortion. Only successful parses are cached; a broken file
re-fails deterministically on every run.

## Decision 4: Cache at the parse layer

The AST cache (`parse_java` in `analyzer_engine.py`) sits at the parse
layer, keyed by sha256 of the source, LRU-bounded at 128 entries.
Parse output depends only on the source text, so a content hash is a
complete key. A detection-layer cache was rejected: detection output
additionally depends on config and detector versions (all would have to
join the cache key), and — worse — cache hits there would skip the
dispatch/detect/helper trace events the replay page is built from.

Costs of the parse-layer cache: one sha256 per run (sub-millisecond for
typical files), bounded memory for up to 128 ASTs, and the constraint
that detectors must treat cached trees as read-only (they are).

### Measured overhead (scripts/benchmark_parse_cache.py)

Synthetic `BigService.java`: 4,803 lines / 141,434 chars, 20 repeated
parses, Python 3.12, javalang 0.13:

| Mode | Total (20 runs) | Per parse |
|---|---|---|
| No cache | 3,518.7 ms | 175.93 ms |
| Parse-layer cache | 216.7 ms | 10.84 ms avg (1 miss + 19 hits ≈ 2.1 ms/hit) |

Repeated analysis of the same large file is ~16x faster overall; a cache
hit costs ~2 ms (hash + lookup) versus ~176 ms for a full reparse.
Reproduce with `python scripts/benchmark_parse_cache.py`.

## Self-check

- `python -m pytest -q` — 16 tests covering registry order, dedup keys,
  parse-failure degradation, cache behavior, helper tracing and
  cross-granularity alignment.
- `python scripts/selfcheck_traceability.py` — runs the batch over the
  repo sample data (`tests/sample_data/java/*.java`) and prints the same
  alignment check the traceability page shows.
- `streamlit run app.py` — upload the sample `.java` files, execute the
  analysis, and open the "Analysis Traceability · 溯源回放" section.
