"""Pytest path setup: support both flat and package import layouts."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
JAVA = SRC / "java_analyzer"
for path in (str(SRC), str(JAVA)):
    if path not in sys.path:
        sys.path.insert(0, path)