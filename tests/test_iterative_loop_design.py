from __future__ import annotations

from anvil.workflows.deep_research_types import ReportType, detect_report_type, detect_target_items


def test_detect_report_type_catalog_patterns():
    q = "Identify 5 providers. Required details: provider website URL, pricing, case study link"
    assert detect_report_type(q) == ReportType.CATALOG


def test_detect_report_type_narrative_default():
    q = "What is MCP and why does it matter for agentic systems?"
    assert detect_report_type(q) == ReportType.NARRATIVE


def test_detect_target_items_parses_number():
    assert detect_target_items("identify 5 business models") == 5
    assert detect_target_items("list 12 tools") == 12
    assert detect_target_items("find 3 providers") == 3
