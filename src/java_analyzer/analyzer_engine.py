"""
Static Analyzer Engine
Core logic for AST parsing, detector dispatch and traceable finding
aggregation.

Pipeline (fully replayable, see :mod:`java_analyzer.runtime`):
    read -> parse (cached) -> dispatch registered detectors in a fixed
    order -> detectors call utils.helpers and record helper hits ->
    findings are keyed and de-duplicated -> aggregated for the dashboard.
"""

import hashlib
import time
from typing import Any, Dict, List, Optional, Tuple

import javalang

# Importing the detector modules triggers decorator registration. Both the
# flat layout (app.py puts src/java_analyzer on sys.path) and the package
# layout (import java_analyzer) are supported.
try:  # pragma: no cover - depends on sys.path wiring
    from detectors import design, implementation, naming_docs  # noqa: F401
    from detectors.base import registered_detectors
    from runtime import ParseCache, DetectionContext
    from utils.helpers import (count_blank_lines, count_comment_lines,
                               stable_hash, severity_rank)
except ImportError:  # pragma: no cover
    from java_analyzer.detectors import design, implementation, naming_docs  # noqa: F401
    from java_analyzer.detectors.base import registered_detectors
    from java_analyzer.runtime import ParseCache, DetectionContext
    from java_analyzer.utils.helpers import (count_blank_lines,
                                             count_comment_lines,
                                             stable_hash, severity_rank)


# Module-level shared cache. Parsing is the expensive, pure step; see the
# ParseCache docstring for the parse-layer vs detection-layer decision.
PARSE_CACHE = ParseCache(max_entries=64)

DEFAULT_CONFIG = {
    'design': True,
    'implementation': True,
    'naming': True,
    'documentation': True,
}


def _content_hash(code: str) -> str:
    return hashlib.sha1(code.encode("utf-8")).hexdigest()[:12]


def empty_metrics(lines: List[str]) -> Dict[str, Any]:
    """Metrics shape returned when no AST is available (parse failure)."""
    total_lines = len(lines)
    blank = count_blank_lines(lines)
    comments = count_comment_lines(lines)
    return {
        'total_classes': 0,
        'total_methods': 0,
        'total_fields': 0,
        'total_lines': total_lines,
        'blank_lines': blank,
        'comment_lines': comments,
        'avg_method_length': 0,
        'max_method_length': 0,
        'avg_complexity': 0,
        'max_complexity': 0,
        'code_lines': max(0, total_lines - blank - comments),
    }


def parse_java(code: str,
               cache: Optional[ParseCache] = None
               ) -> Tuple[Any, bool]:
    """
    Parse Java source into an AST, using the parse-layer cache.

    Returns ``(tree, cache_hit)``. Only successful parses are cached.
    Raises ``ValueError`` on syntax/parse failure.
    """
    cache = cache if cache is not None else PARSE_CACHE
    tree = cache.get(code)
    if tree is not None:
        return tree, True
    try:
        tree = javalang.parse.parse(code)
    except javalang.parser.JavaSyntaxError as exc:
        location = getattr(exc, "at", None)
        description = getattr(exc, "description", "") or "invalid Java syntax"
        raise ValueError(f"Syntax Error at {location}: {description}") from exc
    except Exception as exc:  # pragma: no cover - defensive
        raise ValueError(f"AST Analysis Failed: {exc}") from exc
    cache.put(code, tree)
    return tree, False


def finding_key(file_name: str, issue: Dict[str, Any],
                detector_name: str = "") -> str:
    """
    Deterministic unique key for one finding.

    Key parts: file, detector, rule (Type), target element, source line.
    The human-readable ``Reason`` is intentionally excluded (it often embeds
    counts that can fluctuate without representing a different finding) and
    so is severity (an attribute of the rule, not of the occurrence). This
    guarantees that re-running with a different detector registration order
    never doubles a hit, two rules on the same file stay distinct, and the
    same rule at two locations stays distinct.
    """
    return stable_hash([
        file_name,
        detector_name,
        issue.get("Type"),
        issue.get("Target"),
        issue.get("Line"),
    ])

def analyze_source(code: str,
                   file_name: str = "<memory>",
                   config: Optional[Dict[str, bool]] = None,
                   cache: Optional[ParseCache] = None) -> Dict[str, Any]:
    """
    Analyse one Java source string with full provenance collection.

    A parse failure is *not* raised: it is degraded into one ``Parse Error``
    finding (Critical / ParseError) plus zeroed structural metrics, so a
    batch keeps going and the failed file contributes exactly one count.
    """
    cache = cache if cache is not None else PARSE_CACHE
    config = {**DEFAULT_CONFIG, **(config or {})}
    lines = code.split('\n')
    content_hash = _content_hash(code)
    ctx = DetectionContext(file_name, content_hash)

    started = time.perf_counter()
    ctx.stage("read", bytes=len(code.encode("utf-8")), lines=len(lines),
              content_hash=content_hash)

    tree = None
    cached = False
    parse_error: Optional[str] = None
    parse_started = time.perf_counter()
    try:
        tree, cached = parse_java(code, cache)
    except ValueError as exc:
        parse_error = str(exc)
    parse_ms = (time.perf_counter() - parse_started) * 1000

    if tree is None:
        ctx.stage("parse", status="error", cached=False,
                  duration_ms=round(parse_ms, 3), error=parse_error)
        error_issue = {
            "File": file_name,
            "Type": "Parse Error",
            "Target": file_name,
            "Severity": "Critical",
            "Reason": parse_error,
            "Category": "ParseError",
            "Line": None,
            "Detector": "parser",
            "RuleId": "parse-error",
        }
        error_issue["Key"] = finding_key(file_name, error_issue, "parser")
        ctx.stage("aggregate", status="degraded",
                  raw_findings=1, unique_findings=1)
        ctx.stage("done", status="error",
                  duration_ms=round((time.perf_counter() - started) * 1000, 3))
        return {
            "file_name": file_name,
            "status": "error",
            "tree": None,
            "metrics": empty_metrics(lines),
            "findings": [error_issue],
            "trace": ctx.to_dict(),
            "parse_cached": False,
            "parse_duration_ms": round(parse_ms, 3),
            "duration_ms": round((time.perf_counter() - started) * 1000, 3),
        }

    ctx.stage("parse", cached=cached, duration_ms=round(parse_ms, 3))

    detectors = registered_detectors(config)
    raw_findings: List[Dict[str, Any]] = []
    unique_by_key: Dict[str, Dict[str, Any]] = {}

    for detector in detectors:
        order = getattr(detector, "detector_order", 100)
        category = getattr(detector, "detector_category", "Unknown")
        detector_name = getattr(detector, "detector_name",
                                type(detector).__name__)
        ctx.detector_started(detector_name, order, category)
        try:
            issues = detector.detect(tree, lines, ctx) or []
        except Exception as exc:  # one bad detector must not kill the file
            ctx.detector_failed(detector_name, str(exc))
            continue

        new_raw = 0
        new_unique = 0
        for issue in issues:
            line = issue.get("Line")
            target = issue.get("Target", "")
            ctx.helper_hit(
                helper="detectors.{}.{}".format(detector_name,
                                                issue.get("Type", "")),
                target=target,
                result=True,
                detail=issue.get("Reason", ""),
                line=line,
                detector=detector_name,
                rule_id=issue.get("Type", ""),
                severity=issue.get("Severity", ""),
                produced_finding=True,
            )
            finding = {
                "File": file_name,
                "Type": issue.get("Type", "Unknown"),
                "Target": target,
                "Severity": issue.get("Severity", "Low"),
                "Reason": issue.get("Reason", ""),
                "Category": issue.get("Category", category),
                "Line": line,
                "Detector": detector_name,
                "RuleId": "{}:{}".format(detector_name,
                                         issue.get("Type", "Unknown")),
            }
            finding["Key"] = finding_key(file_name, finding, detector_name)
            raw_findings.append(finding)
            new_raw += 1
            if finding["Key"] not in unique_by_key:
                unique_by_key[finding["Key"]] = finding
                new_unique += 1
        ctx.detector_finished(detector_name, new_raw, new_raw, new_unique)

    findings = sorted(
        unique_by_key.values(),
        key=lambda item: (
            item["File"],
            severity_rank(item["Severity"]),
            item["Detector"],
            item["Type"],
            item["Line"] if item["Line"] is not None else 1 << 30,
            item["Target"],
            item["Key"],
        ),
    )
    ctx.stage("aggregate", raw_findings=len(raw_findings),
              unique_findings=len(findings),
              duplicates_removed=len(raw_findings) - len(findings))

    metrics = StaticAnalyzerEngine(code, config, file_name,
                                   cache).calculate_metrics(tree)
    ctx.stage("done", status="ok",
              duration_ms=round((time.perf_counter() - started) * 1000, 3))

    return {
        "file_name": file_name,
        "status": "ok",
        "tree": tree,
        "metrics": metrics,
        "findings": findings,
        "trace": ctx.to_dict(),
        "parse_cached": cached,
        "parse_duration_ms": round(parse_ms, 3),
        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
    }

def analyze_paths(paths: List[str],
                  config: Optional[Dict[str, bool]] = None,
                  cache: Optional[ParseCache] = None) -> Dict[str, Any]:
    """
    Analyse several Java files; one failure never interrupts the batch.

    Read/OS errors are degraded to one ``Read Error`` finding, mirroring the
    parse-failure contract, so counts stay exact.
    """
    cache = cache if cache is not None else PARSE_CACHE
    files: List[Dict[str, Any]] = []
    for path in paths:
        file_name = path.replace("\\", "/").split("/")[-1]
        try:
            with open(path, "r", encoding="utf-8") as handle:
                code = handle.read()
        except OSError as exc:
            finding = {
                "File": file_name,
                "Type": "Read Error",
                "Target": file_name,
                "Severity": "Critical",
                "Reason": "Could not read file: {}".format(exc),
                "Category": "ParseError",
                "Line": None,
                "Detector": "parser",
                "RuleId": "read-error",
            }
            finding["Key"] = finding_key(file_name, finding, "parser")
            result = {
                "file_name": file_name,
                "status": "read-error",
                "tree": None,
                "metrics": empty_metrics([]),
                "findings": [finding],
                "trace": {
                    "file_name": file_name,
                    "content_hash": "",
                    "events": [
                        {"seq": 1, "kind": "stage", "stage": "read",
                         "status": "error",
                         "detail": {"error": str(exc)}},
                        {"seq": 2, "kind": "stage", "stage": "done",
                         "status": "error", "detail": {}},
                    ],
                    "helper_events": [],
                },
                "parse_cached": False,
                "parse_duration_ms": 0.0,
                "duration_ms": 0.0,
            }
            files.append(result)
            continue
        files.append(analyze_source(code, file_name, config, cache))

    findings = [finding for result in files for finding in result["findings"]]
    findings = sorted(
        findings,
        key=lambda item: (
            item["File"],
            severity_rank(item["Severity"]),
            item["Detector"],
            item["Type"],
            item["Line"] if item["Line"] is not None else 1 << 30,
            item["Key"],
        ),
    )
    return {
        "files": files,
        "findings": findings,
        "cache_stats": cache.stats(),
    }


class StaticAnalyzerEngine:
    """
    Main analyzer engine that orchestrates all code smell detectors
    and calculates comprehensive code metrics.
    """

    def __init__(self, code: str, config: Dict[str, bool] = None,
                 file_name: str = "<memory>",
                 cache: Optional[ParseCache] = None):
        """
        Initialize the analyzer engine.

        Args:
            code: Java source code as a string
            config: Dictionary specifying which detectors to enable
            file_name: Logical file name used in provenance keys
            cache: Parse cache (defaults to the shared module cache)
        """
        self.code = code
        self.lines = code.split('\n')
        self.file_name = file_name
        self.config = {**DEFAULT_CONFIG, **(config or {})}
        self.cache = cache if cache is not None else PARSE_CACHE
        self.detectors = self._initialize_detectors()

    def _initialize_detectors(self):
        """
        Build detectors from the decorator registry, filtered by config.
        Replaces the old hand-maintained if/else factory so adding a
        detector never requires editing the engine.
        """
        return registered_detectors(self.config)

    def run(self) -> Tuple[List[Dict[str, Any]], javalang.tree.CompilationUnit]:
        """
        Run the complete analysis pipeline.

        Returns:
            Tuple of (list of detected issues, parsed AST tree)

        Raises:
            ValueError: If syntax error or parsing fails
        """
        tree, _ = parse_java(self.code, self.cache)

        all_issues: List[Dict[str, Any]] = []
        for detector in self.detectors:
            issues = detector.detect(tree, self.lines)
            for issue in issues or []:
                issue.setdefault("Line", None)
            all_issues.extend(issues or [])

        return all_issues, tree

    def run_traced(self, file_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Run the traceable pipeline (read -> parse -> detect -> aggregate).

        Parse failures degrade to one error finding rather than raising.
        """
        return analyze_source(self.code, file_name or self.file_name,
                              self.config, self.cache)

    def calculate_metrics(self, tree: javalang.tree.CompilationUnit) -> Dict[str, Any]:
        """
        Calculate comprehensive code metrics from the AST.

        Args:
            tree: Parsed Java AST

        Returns:
            Dictionary containing various code metrics
        """
        metrics = {
            'total_classes': 0,
            'total_methods': 0,
            'total_fields': 0,
            'total_lines': len(self.lines),
            'blank_lines': count_blank_lines(self.lines),
            'comment_lines': count_comment_lines(self.lines),
            'avg_method_length': 0,
            'max_method_length': 0,
            'avg_complexity': 0,
            'max_complexity': 0,
            'code_lines': 0
        }

        method_lengths = []
        complexities = []

        # Analyze classes
        for _, node in tree.filter(javalang.tree.ClassDeclaration):
            metrics['total_classes'] += 1

            # Count methods
            if node.methods:
                metrics['total_methods'] += len(node.methods)

                for method in node.methods:
                    # Calculate method length
                    if method.body:
                        length = len(method.body)
                        method_lengths.append(length)

                        # Calculate cyclomatic complexity
                        complexity = self._calculate_complexity(method)
                        complexities.append(complexity)

            # Count fields
            if node.fields:
                metrics['total_fields'] += len(node.fields)

        # Calculate averages
        if method_lengths:
            metrics['avg_method_length'] = sum(method_lengths) / len(method_lengths)
            metrics['max_method_length'] = max(method_lengths)

        if complexities:
            metrics['avg_complexity'] = sum(complexities) / len(complexities)
            metrics['max_complexity'] = max(complexities)

        # Calculate code lines (excluding blanks and comments)
        metrics['code_lines'] = (metrics['total_lines'] -
                                 metrics['blank_lines'] -
                                 metrics['comment_lines'])

        return metrics

    def _calculate_complexity(self, method_node: javalang.tree.MethodDeclaration) -> int:
        """
        Calculate cyclomatic complexity for a method.

        Args:
            method_node: AST node representing a method

        Returns:
            Cyclomatic complexity value
        """
        count = 1
        branch_types = (
            javalang.tree.IfStatement,
            javalang.tree.WhileStatement,
            javalang.tree.DoStatement,
            javalang.tree.ForStatement,
            javalang.tree.CatchClause,
            javalang.tree.SwitchStatementCase,
            javalang.tree.TernaryExpression
        )

        for _, node in method_node.filter(branch_types):
            count += 1

        return count
