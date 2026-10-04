"""
Static Analyzer Engine
Core logic for AST parsing and metric calculation
"""

import hashlib
import time
from collections import OrderedDict

import javalang
from typing import List, Dict, Any, Tuple
from detectors.base import (
    CodeSmell,
    register_detector,
    build_detectors,
    DETECTOR_REGISTRY,
)
from detectors.design import DesignSmells
from detectors.implementation import ImplementationSmells
from detectors.naming_docs import NamingSmells, DocumentationSmells
from utils.helpers import count_blank_lines, count_comment_lines
from traceability import (
    BatchReport,
    TraceRecorder,
    dedup_issues,
    make_error_entry,
    trace_context,
    STEP_READ,
    STEP_PARSE,
    STEP_DISPATCH,
    STEP_DETECT,
    STEP_AGGREGATE,
    STEP_ERROR,
)


# Explicit, ordered detector registration (see detectors/base.py for the
# rationale behind a centralized registry over decorator auto-discovery).
register_detector('design', DesignSmells)
register_detector('implementation', ImplementationSmells)
register_detector('naming', NamingSmells)
register_detector('documentation', DocumentationSmells)


# Parse-layer AST cache.
#
# Decision: caching lives at the parse layer, not the detection layer.
# The parse result depends only on the source text, so a content hash is
# a sufficient key; detection output additionally depends on config and
# detector versions, and caching there would skip the trace events the
# replay page relies on. Cost: one sha256 per run (microseconds) plus
# bounded memory for up to PARSE_CACHE_CAPACITY ASTs; cached trees are
# shared, so detectors must treat them as read-only (they do).
PARSE_CACHE_CAPACITY = 128
_PARSE_CACHE: "OrderedDict[str, javalang.tree.CompilationUnit]" = OrderedDict()
parse_cache_stats: Dict[str, int] = {"hits": 0, "misses": 0}


def parse_java(code: str) -> Tuple[javalang.tree.CompilationUnit, bool]:
    """
    Parse Java source into an AST, using the parse-layer LRU cache.

    Args:
        code: Java source code

    Returns:
        Tuple of (AST tree, cache_hit). Only successful parses are cached;
        syntax errors raise every time.
    """
    key = hashlib.sha256(code.encode('utf-8')).hexdigest()
    cached = _PARSE_CACHE.get(key)
    if cached is not None:
        _PARSE_CACHE.move_to_end(key)
        parse_cache_stats["hits"] += 1
        return cached, True
    parse_cache_stats["misses"] += 1
    tree = javalang.parse.parse(code)
    _PARSE_CACHE[key] = tree
    if len(_PARSE_CACHE) > PARSE_CACHE_CAPACITY:
        _PARSE_CACHE.popitem(last=False)
    return tree, False


def reset_parse_cache() -> None:
    """Clear the parse cache and its statistics (mainly for tests)."""
    _PARSE_CACHE.clear()
    parse_cache_stats["hits"] = 0
    parse_cache_stats["misses"] = 0


class StaticAnalyzerEngine:
    """
    Main analyzer engine that orchestrates all code smell detectors
    and calculates comprehensive code metrics.
    """
    
    def __init__(self, code: str, config: Dict[str, bool] = None,
                 file_name: str = "<memory>", recorder: TraceRecorder = None):
        """
        Initialize the analyzer engine.
        
        Args:
            code: Java source code as a string
            config: Dictionary specifying which detectors to enable
            file_name: Logical name of the file (used for tracing/issues)
            recorder: Optional TraceRecorder capturing pipeline events
        """
        self.code = code
        self.lines = code.split('\n')
        self.file_name = file_name
        self.recorder = recorder
        self.config = config or {
            'design': True,
            'implementation': True,
            'naming': True,
            'documentation': True
        }
        self.detectors: List[CodeSmell] = build_detectors(self.config)
    
    def run(self) -> Tuple[List[Dict[str, Any]], javalang.tree.CompilationUnit]:
        """
        Run the complete analysis pipeline.
        
        Returns:
            Tuple of (list of detected issues, parsed AST tree)
            
        Raises:
            ValueError: If syntax error or parsing fails
        """
        try:
            # Parse the Java source code into an AST (parse-layer cache)
            start = time.perf_counter()
            tree, cache_hit = parse_java(self.code)
            elapsed_ms = (time.perf_counter() - start) * 1000
            if self.recorder:
                self.recorder.record(
                    STEP_PARSE, self.file_name,
                    f"AST parsed ({len(self.lines)} lines, "
                    f"{'cache hit' if cache_hit else 'cache miss'})",
                    cached=cache_hit, elapsed_ms=elapsed_ms)
            
            # Run all detectors
            all_issues = []
            for detector in self.detectors:
                detector_name = type(detector).__name__
                if self.recorder:
                    self.recorder.record(
                        STEP_DISPATCH, self.file_name,
                        f"dispatch {detector_name}")
                issues = detector.detect(tree, self.lines)
                for issue in issues:
                    issue['File'] = self.file_name
                if self.recorder:
                    self.recorder.record(
                        STEP_DETECT, self.file_name,
                        f"{detector_name}: {len(issues)} hit(s)",
                        items=len(issues))
                all_issues.extend(issues)
            
            return all_issues, tree
            
        except javalang.parser.JavaSyntaxError as e:
            raise ValueError(f"Syntax Error at {e.at}: {e.description}")
        except Exception as e:
            raise ValueError(f"AST Analysis Failed: {str(e)}")
    
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


def analyze_batch(files: Dict[str, str], config: Dict[str, bool] = None,
                  recorder: TraceRecorder = None) -> BatchReport:
    """
    Analyze a batch of files with full pipeline tracing.

    Each file goes through read -> parse -> dispatch -> detect -> helper
    decisions, and every step is recorded on the returned report's
    recorder. A file that fails to parse is degraded to a single error
    entry (see traceability.make_error_entry) instead of aborting the
    batch. All issues are deduplicated by traceability.issue_key before
    aggregation, so by-file and by-rule/severity counts stay aligned.

    Args:
        files: Mapping of file name to Java source code
        config: Detector enable/disable configuration
        recorder: Optional external TraceRecorder to append to

    Returns:
        BatchReport with deduplicated issues, metrics, errors and trace
    """
    recorder = recorder or TraceRecorder()
    report = BatchReport(recorder=recorder)
    raw_issues: List[Dict[str, Any]] = []

    for file_name, code in files.items():
        recorder.record(
            STEP_READ, file_name,
            f"read {len(code)} chars / {len(code.splitlines())} lines")

        engine = StaticAnalyzerEngine(
            code, config, file_name=file_name, recorder=recorder)
        with trace_context(recorder, file_name):
            try:
                issues, tree = engine.run()
                report.metrics[file_name] = engine.calculate_metrics(tree)
            except ValueError as exc:
                recorder.record(STEP_ERROR, file_name, str(exc))
                report.errors[file_name] = str(exc)
                issues = [make_error_entry(file_name, str(exc))]
        raw_issues.extend(issues)

    report.issues = dedup_issues(raw_issues)
    recorder.record(
        STEP_AGGREGATE, "<batch>",
        f"aggregated {len(raw_issues)} raw -> {len(report.issues)} unique",
        items=len(report.issues))
    return report
