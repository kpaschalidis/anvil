import json

import pytest

from anvil.workflows.deep_research import DeepResearchConfig, DeepResearchWorkflow, PlanningError
from anvil.subagents.parallel import ParallelWorkerRunner, WorkerResult, WorkerTask


class FakeParallelRunner:
    def spawn_parallel(self, tasks, **kwargs):
        return [
            WorkerResult(
                task_id=t.id,
                output=f"- found for {t.id}: https://example.com/{t.id}",
                citations=(f"https://example.com/{t.id}",),
                web_search_calls=1,
                success=True,
            )
            for t in tasks
        ]


class FakeSubagentRunner:
    def run_task(self, **kwargs):
        return "unused"


def test_deep_research_workflow_fallback_plan(monkeypatch):
    from common import llm as common_llm

    def fake_completion(**kwargs):
        class Msg:
            def __init__(self, content):
                self.content = content

        class Choice:
            def __init__(self, content):
                self.message = Msg(content)

        class Resp:
            def __init__(self, content):
                self.choices = [Choice(content)]

        # return invalid JSON for planning, and a known string for synthesis
        prompt = kwargs["messages"][0]["content"]
        if "research orchestrator" in prompt and '"tasks"' in prompt:
            return Resp("not json")
        return Resp(
            json.dumps(
                {
                    "title": "REPORT",
                    "summary_bullets": ["a"],
                    "findings": [
                        {
                            "claim": "c",
                            "citations": ["https://example.com/overview"],
                        }
                    ],
                    "open_questions": [],
                }
            )
        )

    monkeypatch.setattr(common_llm, "completion", fake_completion)

    wf = DeepResearchWorkflow(
        subagent_runner=FakeSubagentRunner(),  # type: ignore[arg-type]
        parallel_runner=FakeParallelRunner(),  # type: ignore[arg-type]
        config=DeepResearchConfig(
            model="gpt-4o",
            max_workers=2,
            worker_max_iterations=2,
            worker_timeout_s=10.0,
            best_effort=True,
        ),
        emitter=None,
    )
    outcome = wf.run("query")
    assert outcome.report_markdown.startswith("# REPORT")
    assert "## Sources" in outcome.report_markdown
    assert "[1]" in outcome.report_markdown
    assert "Why:" in outcome.report_markdown


def test_deep_research_workflow_planning_code_fence_json_parses(monkeypatch):
    from common import llm as common_llm

    def fake_completion(**kwargs):
        class Msg:
            def __init__(self, content):
                self.content = content

        class Choice:
            def __init__(self, content):
                self.message = Msg(content)

        class Resp:
            def __init__(self, content):
                self.choices = [Choice(content)]

        prompt = kwargs["messages"][0]["content"]
        if "research orchestrator" in prompt:
            return Resp(
                "```json\n"
                + json.dumps(
                    {
                        "tasks": [
                            {"id": "a", "search_query": "q1", "instructions": "i1"},
                            {"id": "b", "search_query": "q2", "instructions": "i2"},
                            {"id": "c", "search_query": "q3", "instructions": "i3"},
                        ]
                    }
                )
                + "\n```"
            )
        return Resp(
            json.dumps(
                {
                    "title": "REPORT",
                    "summary_bullets": ["a"],
                    "findings": [
                        {
                            "claim": "c",
                            "citations": ["https://example.com/a"],
                        }
                    ],
                    "open_questions": [],
                }
            )
        )

    monkeypatch.setattr(common_llm, "completion", fake_completion)

    wf = DeepResearchWorkflow(
        subagent_runner=FakeSubagentRunner(),  # type: ignore[arg-type]
        parallel_runner=FakeParallelRunner(),  # type: ignore[arg-type]
        config=DeepResearchConfig(model="gpt-4o", max_workers=2, worker_max_iterations=2, worker_timeout_s=10.0),
        emitter=None,
    )
    outcome = wf.run("query")
    assert outcome.plan["tasks"][0]["id"] == "a"


def test_deep_research_workflow_planning_invalid_json_is_error(monkeypatch):
    from common import llm as common_llm

    def fake_completion(**kwargs):
        class Msg:
            def __init__(self, content):
                self.content = content

        class Choice:
            def __init__(self, content):
                self.message = Msg(content)

        class Resp:
            def __init__(self, content):
                self.choices = [Choice(content)]

        return Resp("not json")

    monkeypatch.setattr(common_llm, "completion", fake_completion)

    wf = DeepResearchWorkflow(
        subagent_runner=FakeSubagentRunner(),  # type: ignore[arg-type]
        parallel_runner=FakeParallelRunner(),  # type: ignore[arg-type]
        config=DeepResearchConfig(model="gpt-4o", max_workers=2, worker_max_iterations=2, worker_timeout_s=10.0),
        emitter=None,
    )
    with pytest.raises(PlanningError):
        wf.run("query")


def test_deep_research_workflow_planning_validation_error_preserves_raw(monkeypatch):
    from common import llm as common_llm

    def fake_completion(**kwargs):
        class Msg:
            def __init__(self, content):
                self.content = content

        class Choice:
            def __init__(self, content):
                self.message = Msg(content)

        class Resp:
            def __init__(self, content):
                self.choices = [Choice(content)]

        prompt = kwargs["messages"][0]["content"]
        if "research orchestrator" in prompt:
            # parses, but invalid tasks (missing instructions/search_query)
            return Resp(json.dumps({"tasks": [{"id": "a"}]}))
        return Resp(
            json.dumps(
                {
                    "title": "REPORT",
                    "summary_bullets": ["a"],
                    "findings": [],
                    "open_questions": [],
                }
            )
        )

    monkeypatch.setattr(common_llm, "completion", fake_completion)

    wf = DeepResearchWorkflow(
        subagent_runner=FakeSubagentRunner(),  # type: ignore[arg-type]
        parallel_runner=FakeParallelRunner(),  # type: ignore[arg-type]
        config=DeepResearchConfig(model="gpt-4o", max_workers=2, worker_max_iterations=2, worker_timeout_s=10.0),
        emitter=None,
    )
    with pytest.raises(PlanningError) as e:
        wf.run("query")
    assert e.value.raw
