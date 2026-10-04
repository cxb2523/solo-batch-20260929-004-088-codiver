"""Benchmark: repeated parsing of a large Java file, with and without
the parse-layer AST cache in analyzer_engine.parse_java.

Usage: python scripts/benchmark_parse_cache.py
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "java_analyzer"))

import javalang  # noqa: E402
from analyzer_engine import parse_java, reset_parse_cache  # noqa: E402

REPEATS = 20


def generate_large_source(num_methods: int = 800) -> str:
    lines = ["public class BigService {", "    private int state = 0;"]
    for i in range(num_methods):
        lines.append(f"    public int method{i}(int x) {{")
        lines.append(f"        int y = x + {i};")
        lines.append("        if (y > 10) { y = y - 1; } else { y = y + 1; }")
        lines.append("        while (y > 100) { y = y / 2; }")
        lines.append("        return y;")
        lines.append("    }")
    lines.append("}")
    return "\n".join(lines)


def main() -> None:
    code = generate_large_source()
    num_lines = len(code.splitlines())
    print(f"Sample: BigService.java, {num_lines} lines, {len(code)} chars")
    print(f"Repeats: {REPEATS}\n")

    start = time.perf_counter()
    for _ in range(REPEATS):
        javalang.parse.parse(code)
    cold_total = (time.perf_counter() - start) * 1000

    reset_parse_cache()
    start = time.perf_counter()
    for _ in range(REPEATS):
        parse_java(code)
    warm_total = (time.perf_counter() - start) * 1000

    cold_avg = cold_total / REPEATS
    warm_avg = warm_total / REPEATS
    print(f"No cache  : {cold_total:8.1f} ms total, {cold_avg:7.2f} ms/parse")
    print(f"With cache: {warm_total:8.1f} ms total, {warm_avg:7.3f} ms/parse "
          f"(1 miss + {REPEATS - 1} hits)")
    print(f"Speedup   : {cold_avg / warm_avg:.0f}x on repeated analysis")


if __name__ == "__main__":
    main()
