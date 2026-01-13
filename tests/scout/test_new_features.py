import pytest

from scout.cost import CostTracker, Usage
from scout.models import PainSnippet
from scout.session import SessionManager
from scout.validation import SnippetValidator, SnippetValidationConfig


def test_cost_tracker_accumulates_totals():
    tracker = CostTracker()
    tracker.record(kind="extraction", usage=Usage(total_tokens=100, cost_usd=0.01))
    tracker.record(kind="complexity", usage=Usage(total_tokens=10, cost_usd=0.001))

    totals = tracker.totals()
    assert totals.calls == 2
    assert totals.total_tokens == 110
    assert totals.total_cost_usd == pytest.approx(0.011)
    assert totals.calls_by_kind["extraction"] == 1
    assert totals.calls_by_kind["complexity"] == 1


def test_snippet_validator_filters_and_dedupes():
    validator = SnippetValidator(
        SnippetValidationConfig(
            min_confidence=0.5, min_excerpt_length=3, min_pain_statement_length=3
        )
    )
    snippets = [
        PainSnippet(
            doc_id="doc:1",
            excerpt="okay",
            pain_statement="same",
            signal_type="complaint",
            intensity=3,
            confidence=0.9,
        ),
        PainSnippet(
            doc_id="doc:1",
            excerpt="okay",
            pain_statement="same",
            signal_type="complaint",
            intensity=3,
            confidence=0.9,
        ),
        PainSnippet(
            doc_id="doc:1",
            excerpt="okay",
            pain_statement="low",
            signal_type="complaint",
            intensity=3,
            confidence=0.1,
        ),
    ]

    kept, dropped = validator.validate(snippets)
    assert len(kept) == 1
    assert dropped == 2


def test_session_manager_clone_and_tags(tmp_path):
    manager = SessionManager(str(tmp_path))
    session = manager.create_session("topic", max_iterations=10)

    manager.tag_session(session.session_id, ["a", "b"])
    tagged = manager.load_session(session.session_id)
    assert tagged is not None
    assert tagged.tags == ["a", "b"]

    cloned = manager.clone_session(session.session_id, topic="new topic")
    assert cloned.parent_session_id == session.session_id
    assert cloned.topic == "new topic"
    assert cloned.tags == ["a", "b"]
