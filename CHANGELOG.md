# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]
### Added
- End-to-end finding traceability for the Java analyzer: a new
  "Finding Traceability" dashboard page replays the read -> parse ->
  detector dispatch -> helper decision -> aggregation chain, with a
  by-file / by-rule(severity) granularity toggle whose counts are
  verified to align.
- Decorator-based detector registry (`@register_detector`) with explicit
  dispatch order independent of import order.
- Content-addressed LRU parse cache at the parse layer
  (`java_analyzer.runtime.ParseCache`).
- Deterministic unique finding keys (file/detector/rule/target/line) with
  de-duplication.
- Parse/read failures degrade to a single error entry instead of
  interrupting a batch.
- Pytest coverage for the registry, pipeline, aggregation alignment,
  cache behavior, and Streamlit trace page; benchmark script for repeated
  parsing cost.

## [1.0.0] - 2024-05-10
### Added
- Initial release of Software Metrics Calculator.
- Support for Python file analysis (LOC, Cyclomatic Complexity, Cognitive Complexity).
- COCOMO estimation model.
- Agile metrics analysis (Velocity, Scope Creep).
- Streamlit dashboard for visualization.
- Export metrics to CSV.
