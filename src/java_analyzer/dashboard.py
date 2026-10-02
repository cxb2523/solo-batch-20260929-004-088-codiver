"""
Enterprise Java Static Analyzer Pro
Main Entry Point - Streamlit UI Application

This is the main entry point that coordinates the UI and analysis engine.
Run with: streamlit run app.py
"""

import streamlit as st
import pandas as pd
from datetime import datetime

from analyzer_engine import StaticAnalyzerEngine
from traceability import build_trace_views, pipeline_timeline
from detectors.base import registry_snapshot
from utils.ui_components import (
    render_executive_summary,
    render_code_metrics,
    render_visualizations,
    render_detailed_findings,
    render_source_code_viewer,
    render_summary_report,
    render_landing_page
)
from utils.helpers import format_file_size


def initialize_session_state():
    """Initialize session state variables for persistent data storage."""
    if 'analysis_results' not in st.session_state:
        st.session_state.analysis_results = None
    if 'analysis_metrics' not in st.session_state:
        st.session_state.analysis_metrics = None
    if 'analysis_findings' not in st.session_state:
        st.session_state.analysis_findings = None
    if 'analysis_trace' not in st.session_state:
        st.session_state.analysis_trace = None
    if 'source_code' not in st.session_state:
        st.session_state.source_code = None
    if 'file_name' not in st.session_state:
        st.session_state.file_name = None


def configure_page():
    """Configure Streamlit page settings and custom CSS."""

    
    # Custom CSS styling
    st.markdown("""
        <style>
        .main-header {
            font-size: 2.5rem;
            font-weight: 700;
            background: linear-gradient(120deg, #1e3a8a 0%, #3b82f6 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 0.5rem;
        }
        .subtitle {
            color: #64748b;
            font-size: 1.1rem;
            margin-bottom: 2rem;
        }
        </style>
    """, unsafe_allow_html=True)


def render_header():
    """Render the main application header."""
    st.markdown('<h1 class="main-header">  Java Static Analyzer</h1>', 
                unsafe_allow_html=True)
    st.markdown('<p class="subtitle">Advanced Technical Debt Detection & Code Quality Intelligence Platform</p>', 
                unsafe_allow_html=True)


def render_sidebar():
    """
    Render the sidebar with file upload and configuration options.
    
    Returns:
        Tuple of (uploaded_file, analyze_button_clicked, config_dict)
    """
    with st.sidebar:
        st.markdown("###  Control Center")
        
        # File uploader
        uploaded_file = st.file_uploader(
            "Upload Java Source File",
            type=["java"],
            help="Select a .java file for comprehensive analysis"
        )
        
        st.markdown("---")
        
        # Analysis configuration
        with st.expander(" Analysis Configuration"):
            enable_design = st.checkbox("Design Smells", value=True)
            enable_implementation = st.checkbox("Implementation Smells", value=True)
            enable_naming = st.checkbox("Naming Conventions", value=True)
            enable_documentation = st.checkbox("Documentation", value=True)
        
        config = {
            'design': enable_design,
            'implementation': enable_implementation,
            'naming': enable_naming,
            'documentation': enable_documentation
        }
        
        # Analyze button
        analyze_btn = st.button(
            " [START]  Run Deep Analysis",
            type="primary",
            use_container_width=True
        )
        
        st.markdown("---")
        
        # Analysis scope information
        st.markdown("###  Analysis Scope")
        st.markdown("""
        - ✅ Design Pattern Violations
        - ✅ Cyclomatic Complexity
        - ✅ Code Smell Detection
        - ✅ Naming Conventions
        - ✅ Documentation Coverage
        - ✅ Maintainability Index
        """)
        
        st.markdown("---")
        
        # Version and timestamp
        st.caption(" Ahmad Hassan")
        st.caption(" Muhammad Abdullah")
        st.caption(" Nayyar Abbas")
        st.caption(" Faraz Ashraf")
        st.caption(" Ahsan Ali Khan")
        st.caption(f" {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    return uploaded_file, analyze_btn, config


def render_file_info(file_name: str, file_size: int, line_count: int):
    """
    Render file information metrics.
    
    Args:
        file_name: Name of the uploaded file
        file_size: Size of the file in bytes
        line_count: Number of lines in the file
    """
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.info(f" **File:** {file_name}")
    with col2:
        st.info(f" **Size:** {file_size} bytes")
    with col3:
        st.info(f" **Lines:** {line_count}")


def handle_analysis(source_code: str, config: dict = None):
    """
    Handle the analysis execution and error handling.
    
    Args:
        source_code: Java source code to analyze
        config: Analysis configuration dictionary
    """
    file_name = st.session_state.get("file_name") or "<memory>"
    engine = StaticAnalyzerEngine(source_code, config, file_name=file_name)

    with st.spinner(" Parsing AST nodes and executing analyzers..."):
        # Traceable pipeline. A parse failure degrades to one error finding
        # instead of interrupting, so the page always gets consistent data.
        outcome = engine.run_traced(file_name)

        st.session_state.analysis_results = outcome["findings"]
        st.session_state.analysis_metrics = outcome["metrics"]
        st.session_state.analysis_findings = outcome["findings"]
        st.session_state.analysis_trace = outcome["trace"]

        if outcome["status"] != "ok":
            st.warning(
                f"⚠️ **Parse issue in {file_name}:** recorded one error "
                "entry; the rest of the batch remains unaffected."
            )


def display_analysis_results():
    """Display all analysis results from session state."""
    if st.session_state.analysis_results is not None:
        results = st.session_state.analysis_findings or st.session_state.analysis_results
        metrics = st.session_state.analysis_metrics
        df = pd.DataFrame(results) if results else pd.DataFrame()
        
        # Render all dashboard sections
        render_executive_summary(df, metrics)
        st.markdown("---")
        
        render_code_metrics(metrics)
        st.markdown("---")
        
        render_visualizations(df)
        st.markdown("---")
        
        render_detailed_findings(df)

        st.markdown("---")

        render_trace_page(
            st.session_state.analysis_findings or results,
            st.session_state.analysis_trace,
        )
        
        # Source code viewer
        render_source_code_viewer(st.session_state.source_code)
        
        # Summary report
        render_summary_report(df, metrics, st.session_state.file_name)


def render_trace_page(findings, trace):
    """
    Render the provenance / traceability page.

    Every pipeline hit (read -> parse -> detector dispatch -> helper
    decision -> aggregated finding) is replayable here. A granularity
    toggle switches between per-file and per-rule/severity aggregation;
    the two sides are built from the same de-duplicated finding list and
    an alignment check confirms their counts match.
    """
    st.markdown("###  Finding Traceability")

    if not findings:
        st.success(" No findings to trace - clean analysis.")
        return

    views = build_trace_views(findings)

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Unique Findings", views["total"])
    with col2:
        st.metric("By File Total", views["file_total"])
    with col3:
        st.metric("By Rule Total", views["rule_total"])

    if views["aligned"]:
        st.success(
            f" Counts aligned: {views['file_total']} (by file) == "
            f"{views['rule_total']} (by rule/severity) == {views['total']} "
            "unique findings."
        )
    else:
        st.error(
            " Count mismatch between granularities - the unique key or "
            "aggregation is inconsistent."
        )

    sev = views["severity"]
    st.caption(
        f"Critical {sev['Critical']} | High {sev['High']} | "
        f"Medium {sev['Medium']} | Low {sev['Low']}"
    )

    granularity = st.radio(
        "Aggregation granularity",
        options=["By file", "By rule/severity"],
        horizontal=True,
    )

    if granularity == "By file":
        st.dataframe(pd.DataFrame(views["by_file"]),
                     use_container_width=True, hide_index=True)
    else:
        st.dataframe(pd.DataFrame(views["by_rule"]),
                     use_container_width=True, hide_index=True)

    st.markdown("#### Pipeline replay")
    if trace is not None:
        st.caption(
            f"File: {trace.get('file_name')} | "
            f"content hash: {trace.get('content_hash')}"
        )
        timeline = pipeline_timeline(trace)
        st.dataframe(pd.DataFrame(timeline)[
            ["seq", "Layer", "Step", "Status", "Detail"]
        ], use_container_width=True, hide_index=True, height=320)
    else:
        st.info("No per-file trace available for this run.")

    with st.expander(" Detector registry (fixed dispatch order)"):
        st.dataframe(pd.DataFrame(registry_snapshot()),
                     use_container_width=True, hide_index=True)

    with st.expander(" Provenance entries (one row per unique finding)"):
        provenance = [{
            "Key": item["Key"],
            "File": item["File"],
            "Detector": item["Detector"],
            "RuleId": item["RuleId"],
            "Type": item["Type"],
            "Severity": item["Severity"],
            "Target": item["Target"],
            "Line": item["Line"],
            "Reason": item["Reason"],
        } for item in findings]
        st.dataframe(pd.DataFrame(provenance),
                     use_container_width=True, hide_index=True, height=320)


def main():
    """Main application entry point."""
    # Initialize
    initialize_session_state()
    configure_page()
    
    # Render header
    render_header()
    
    # Render sidebar and get inputs
    uploaded_file, analyze_btn, config = render_sidebar()
    
    # Main application logic
    if uploaded_file:
        source_code = uploaded_file.getvalue().decode("utf-8")
        
        # Check if this is a new file
        if st.session_state.file_name != uploaded_file.name:
            st.session_state.file_name = uploaded_file.name
            st.session_state.source_code = source_code
            # Reset analysis when new file is uploaded
            st.session_state.analysis_results = None
            st.session_state.analysis_metrics = None
            st.session_state.analysis_findings = None
            st.session_state.analysis_trace = None
        
        # Display file information
        render_file_info(
            uploaded_file.name,
            len(source_code),
            len(source_code.split('\n'))
        )
        
        # Handle analysis button click
        if analyze_btn:
            handle_analysis(source_code)
        
        # Display results if they exist
        display_analysis_results()
    
    else:
        # Show landing page when no file is uploaded
        render_landing_page()


if __name__ == "__main__":
    main()
