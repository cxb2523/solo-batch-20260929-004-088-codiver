# Analysis Traceability — Design Decisions

The Java pipeline (`read -> parse -> dispatch detectors -> helper
judgements -> aggregate findings`) is fully replayable on the new
**Finding Traceability** page in `src/java_analyzer/dashboard.py`. This page
switches between two granularities (by file, by rule/severity) and asserts
that both sides, plus the flat unique-finding count, are identical.

The four decisions that make that possible are recorded here.

## 1. Detector registry: decorator auto-discovery, explicit order

* **Decision:** decorator auto-discovery, not a central hand-maintained
  list. Each detector is annotated
  `@register_detector(name, category, order, config_key)` in
  `src/java_analyzer/detectors/base.py`; importing the detector modules
  registers them once. Registration is idempotent per detector name, so
  double-importing a module (the app puts both `src` and
  `src/java_analyzer` on `sys.path`) cannot double-register.
* **Ordering:** every registration carries an explicit integer `order`
  (`design=10`, `implementation=20`, `naming=30`, `documentation=40`).
  `registered_detectors()` and `registry_snapshot()` **re-sort** by
  `(order, name)` defensively. Module import order therefore cannot change
  dispatch order.
* **Effect on entries / de-duplication:** registration order does **not**
  change the unique-key computation or de-duplication (keys are content
  based, see below) and does not change the *set* of entries. It only
  determines the chronological order of trace events; the aggregated
  findings list is re-sorted deterministically by
  `(file, severity, detector, rule, line, key)`, so the final order is
  stable regardless of dispatch order. Tests:
  `tests/test_registry.py`, `test_repeated_runs_and_registry_reorder_keep_keys_stable`.

## 2. Unique key for multiple rules on one file

* **Decision:** `key = sha1(file | detector | rule(Type) | target | line)`
  (`analyzer_engine.finding_key`, via `utils.helpers.stable_hash`).
* `Reason` is excluded (it embeds counts that can fluctuate without
  representing a new finding) and `Severity` is excluded (an attribute of
  the rule, not of the occurrence).
* Different rules against the same element stay distinct because
  `detector/rule` participates; the same rule at two locations stays
  distinct because `line/target` participates; identical hits emitted twice
  (or in two registrations) collapse to one because the hash is identical.
* Because both granularities are computed from this single de-duplicated
  list, `sum(by_file.Issues) == sum(by_rule.Issues) == len(findings)`
  always holds (verified by `build_trace_views(..., aligned=True)` and
  `tests/test_traceability.py`).

## 3. Single-file parse failure: degrade to one error entry

* **Decision:** neither skip nor abort. A parse failure is converted into
  exactly one `Parse Error` finding (`Severity=Critical`,
  `Category=ParseError`, `Detector=parser`, `RuleId=parse-error`) with
  zeroed structural metrics, so the batch keeps going and the file
  contributes exactly one count to both granularities. Read/OS errors use
  the same contract (`Read Error`).
* The error entry goes through the same key/dedup path and appears on the
  trace timeline (`parse` stage, status `error`; `aggregate` stage marked
  `degraded`). Tests: `test_parse_failure_degrades_to_one_error_entry`,
  `test_batch_continues_after_one_bad_file`,
  `test_parse_error_counted_exactly_once_per_bad_file`.

## 4. Large-file repeat parsing: measured cost + cache placement

Measured with `tests/benchmark_parse_cache.py` on a generated **46.4 KB /
2002-line / 400-method** file (5-run averages on this machine):

| Operation | Avg time |
| --- | --- |
| Uncached `javalang.parse.parse` | ~44 ms |
| Parse-cache hit (identical content) | ~0.001 ms |
| Full analysis cold (parse + all detectors) | ~161 ms |
| Full analysis warm (detectors walk cached AST) | ~111 ms |

* **Decision:** cache at the **parse layer** (`runtime.ParseCache`, a
  bounded LRU keyed by source content; default 64 entries, shared at module
  level in `analyzer_engine.PARSE_CACHE`).
* Why parse layer: parsing is the expensive, pure `text -> AST` step and is
  shared by every detector. Caching the AST once removes essentially all
  repeated parse cost while keeping detectors stateless and re-runnable.
* Cost/trade-offs:
  * Memory: up to `max_entries` AST trees retained (bounded, LRU-evicted).
  * Only successful parses are cached; failures are retried on each run.
  * A detection-layer cache would store one result set per
    `(file, enabled-detector-set)` and a duplicate AST per combination,
    would save only the detector walk (~111 ms here) while still paying the
    first ~44 ms parse, and would be invalidated by any config toggle.