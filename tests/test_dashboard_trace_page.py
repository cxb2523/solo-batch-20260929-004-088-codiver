"""Trace page renders in Streamlit and both granularities show aligned counts."""

from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest

import dashboard

SAMPLES = Path(__file__).resolve().parent / "sample_data"


def _run_dashboard(source_file):
    code = (SAMPLES / source_file).read_text(encoding="utf-8")
    script = f"""
import sys
sys.path.insert(0, {str(SAMPLES.parents[1] / 'src')!r})
sys.path.insert(0, {str(SAMPLES.parents[1] / 'src' / 'java_analyzer')!r})
import dashboard
code = {code!r}
dashboard.initialize_session_state()
dashboard.st.session_state.file_name = {source_file!r}
dashboard.handle_analysis(code, None)
dashboard.display_analysis_results()
"""

    at = AppTest.from_string(script, default_timeout=15)
    at.run()
    return at


def test_trace_page_renders_alignment_and_registry():
    at = _run_dashboard("god_class.java")
    assert not at.exception, [str(e) for e in at.exception]

    markdowns = " ".join(m.value for m in at.markdown)
    assert "Finding Traceability" in markdowns
    successes = " ".join(s.value for s in at.success)
    assert "Counts aligned" in successes

    # Registry expander lists the four detectors in fixed order.
    assert any(len(df.value) >= 4 for df in at.dataframe)


def test_granularity_toggle_switches_views():
    at = _run_dashboard("god_class.java")
    assert not at.exception

    # Default radio is "By file"; switch to rule view and re-run.
    radio = at.radio[0]
    radio.set_value("By rule/severity").run()
    assert not at.exception
    successes = " ".join(s.value for s in at.success)
    assert "Counts aligned" in successes


def test_parse_failure_shows_warning_and_still_aligns():
    at = _run_dashboard("broken_syntax.java")
    assert not at.exception
    successes = " ".join(s.value for s in at.success)
    assert "Counts aligned" in successes
    assert at.warning  # degraded-entry warning shown


def test_clean_file_does_not_crash_executive_summary():
    at = _run_dashboard("clean.java")
    assert not at.exception
