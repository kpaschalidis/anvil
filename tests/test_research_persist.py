from pathlib import Path

from anvil.workflows.research_persist import persist_research_outcome


class _R:
    def __init__(self, task_id: str):
        self.task_id = task_id
        self.success = True
        self.error = None
        self.web_search_calls = 1
        self.citations = ("https://example.com",)
        self.output = "x"


class _Outcome:
    def __init__(self):
        self.plan = {"tasks": []}
        self.results = [_R("a")]
        self.report_markdown = "# R\n"
        self.synthesis_input = {"query": "q", "allowed_sources": [], "tasks": []}
        self.rounds = [
            {
                "round_index": 1,
                "stage": "discovery",
                "plan": {"tasks": [{"id": "task1", "search_query": "q", "instructions": "i"}]},
                "planner_raw": '{"tasks":[{"id":"task1","search_query":"q","instructions":"i"}]}',
                "planner_error": None,
                "task_ids": ["a"],
                "memo": {"query": "q", "report_type": "narrative", "gaps": []},
            }
        ]


def test_persist_research_outcome_writes_session_layout(tmp_path: Path):
    paths = persist_research_outcome(
        data_dir=str(tmp_path),
        session_id="abc123",
        meta={"kind": "research"},
        outcome=_Outcome(),
        output_path=None,
        save_artifacts=True,
    )
    assert paths["session_dir"].exists()
    assert (tmp_path / "abc123" / "meta.json").exists()
    assert (tmp_path / "abc123" / "research" / "plan.json").exists()
    assert (tmp_path / "abc123" / "research" / "workers" / "a.json").exists()
    assert (tmp_path / "abc123" / "research" / "report.md").exists()
    assert (tmp_path / "abc123" / "research" / "synthesis_input.json").exists()


def test_persist_research_outcome_writes_round_artifacts(tmp_path: Path):
    persist_research_outcome(
        data_dir=str(tmp_path),
        session_id="abc123",
        meta={"kind": "research"},
        outcome=_Outcome(),
        output_path=None,
        save_artifacts=True,
    )
    round_dir = tmp_path / "abc123" / "research" / "rounds" / "round_01"
    assert (round_dir / "meta.json").exists()
    assert (round_dir / "plan.json").exists()
    assert (round_dir / "memo.json").exists()
    assert (round_dir / "planner_raw.txt").exists()
    assert (round_dir / "workers" / "a.json").exists()
