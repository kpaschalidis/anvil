from __future__ import annotations

from anvil.workflows.iterative_loop import (
    CatalogMemo,
    ClaimToVerify,
    Gap,
    ReportType,
    ResearchMemo,
    SourceEntry,
    detect_report_type,
    detect_required_fields,
    detect_target_items,
    memo_to_planner_context,
)


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


def test_detect_required_fields_parses_block():
    q = "Required details for each service: name & provider, Provider website URL, Pricing model, Link to case studies"
    fields = detect_required_fields(q)
    assert "Provider website URL" in fields
    assert "Pricing model" in fields


def test_memo_to_planner_context_is_bounded():
    memo = ResearchMemo(
        query="x" * 5000,
        report_type=ReportType.NARRATIVE,
        round_index=2,
        tasks_completed=6,
        tasks_remaining=6,
        unique_citations=20,
        unique_domains=12,
        pages_extracted=10,
        themes_covered=("a", "b", "c", "d", "e", "f"),
        sources_summary=tuple(
            SourceEntry(url=f"https://example{i}.com", domain=f"example{i}.com", title="t") for i in range(50)
        ),
        gaps=tuple(Gap(gap_type="missing_topic", description=f"gap{i}", priority=2) for i in range(50)),
        claims_to_verify=(
            ClaimToVerify(claim_text="c", source_url="https://s.com", verification_query="q"),
        ),
    )
    text = memo_to_planner_context(memo, max_chars=1200)
    assert len(text) <= 1220
    assert "memo truncated" in text


def test_catalog_memo_renders_candidates_section():
    memo = CatalogMemo(
        query="q",
        report_type=ReportType.CATALOG,
        round_index=1,
        tasks_completed=3,
        tasks_remaining=9,
        unique_citations=10,
        unique_domains=8,
        pages_extracted=6,
        target_items=5,
    )
    text = memo_to_planner_context(memo)
    assert "Candidates" in text

