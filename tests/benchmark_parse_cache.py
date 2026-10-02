"""
Measured cost of repeatedly parsing a large Java file.

Run directly:  python tests/benchmark_parse_cache.py

Compares three strategies on the same generated source:
  1. no cache        - javalang re-parses the text every time;
  2. parse cache     - AST parsed once, reused on identical content;
  3. detector cache  - cached detection results skip the detector walk but
                       the first (and every config-changing) parse remains.

Decision: cache at the parse layer. Parsing dominates the repeated cost and
is the only pure step; detector results are cheap to recompute by walking a
shared tree, while caching them multiplies memory by the number of
(config x file) combinations and never avoids the first parse.
"""

import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "src" / "java_analyzer"))

import javalang  # noqa: E402

from analyzer_engine import analyze_source, parse_java, ParseCache  # noqa: E402


def build_large_source(methods: int = 400) -> str:
    body = "\n".join(
        f"    public int op{i}(int x) {{\n"
        f"        int y = {i % 97};\n"
        f"        if (x > y) {{ return x + y + {i % 7}; }}\n"
        f"        return x - y;\n"
        f"    }}"
        for i in range(methods)
    )
    return f"public class BigService {{\n{body}\n}}\n"


def time_ms(fn, repeat: int) -> float:
    samples = []
    for _ in range(repeat):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000)
    return statistics.mean(samples)


def main(runs: int = 5):
    source = build_large_source()
    size_kb = len(source.encode("utf-8")) / 1024
    print(f"Generated source: {size_kb:.1f} KB, "
          f"{source.count(chr(10))} lines")

    # 1. Raw parsing without cache (javalang every time).
    no_cache_ms = time_ms(lambda: javalang.parse.parse(source), runs)

    # 2. Parse-layer cache: one cold parse, subsequent calls are hits.
    parse_cache = ParseCache()
    parse_java(source, parse_cache)  # prime
    cached_parse_ms = time_ms(lambda: parse_java(source, parse_cache), runs)

    # 3. Full analysis: cold (parse + detect) vs warm (detect over cached AST).
    cold_analysis_ms = time_ms(
        lambda: analyze_source(source, "BigService.java",
                               cache=ParseCache()),
        runs)
    prime_cache = ParseCache()
    analyze_source(source, "BigService.java", cache=prime_cache)
    warm_analysis_ms = time_ms(
        lambda: analyze_source(source, "BigService.java",
                               cache=prime_cache),
        runs)

    detection_walk_ms = warm_analysis_ms  # warm = detector walk + aggregation
    speedup = no_cache_ms / cached_parse_ms if cached_parse_ms else float("inf")
    print(f"Uncached parse (avg): {no_cache_ms:.2f} ms")
    print(f"Cached parse hit (avg): {cached_parse_ms:.4f} ms")
    print(f"Parse speedup: {speedup:.0f}x | cache stats: {parse_cache.stats()}")
    print(f"Full analysis cold (avg): {cold_analysis_ms:.2f} ms")
    print(f"Full analysis warm (avg): {warm_analysis_ms:.2f} ms "
          f"(~{detection_walk_ms:.2f} ms detector walk from shared AST)")
    print("Decision: cache the AST at the parse layer. A detection-layer "
          "cache would save the detector walk but never the first parse, "
          "and stores one AST per (file, config) combination.")


if __name__ == "__main__":
    main()
