import json

import pytest

from anvil.workflows.deep_research import DeepResearchConfig, DeepResearchWorkflow, PlanningError
from anvil.workflows.deep_research import sanitize_snippet
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
        config=DeepResearchConfig(
            model="gpt-4o",
            max_workers=2,
            worker_max_iterations=2,
            worker_timeout_s=10.0,
            min_total_domains=0,
        ),
        emitter=None,
    )
    outcome = wf.run("query")
    assert outcome.plan["tasks"][0]["id"] == "a"


def test_deep_research_workflow_synthesis_code_fence_json_parses(monkeypatch):
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
                json.dumps(
                    {
                        "tasks": [
                            {"id": "a", "search_query": "q1", "instructions": "i1"},
                            {"id": "b", "search_query": "q2", "instructions": "i2"},
                            {"id": "c", "search_query": "q3", "instructions": "i3"},
                        ]
                    }
                )
            )
        if "research synthesizer" in prompt:
            return Resp(
                "```json\n"
                + json.dumps(
                    {
                        "title": "REPORT",
                        "summary_bullets": ["a"],
                        "findings": [{"claim": "c", "citations": ["https://example.com/a"]}],
                        "open_questions": [],
                    }
                )
                + "\n```"
            )
        return Resp("{}")

    monkeypatch.setattr(common_llm, "completion", fake_completion)

    wf = DeepResearchWorkflow(
        subagent_runner=FakeSubagentRunner(),  # type: ignore[arg-type]
        parallel_runner=FakeParallelRunner(),  # type: ignore[arg-type]
        config=DeepResearchConfig(
            model="gpt-4o",
            max_workers=2,
            worker_max_iterations=2,
            worker_timeout_s=10.0,
            min_total_domains=0,
            min_total_citations=1,
        ),
        emitter=None,
    )
    outcome = wf.run("query")
    assert outcome.report_markdown.startswith("# REPORT")


def test_sanitize_snippet_removes_relative_links_and_markdown_nav():
    raw = (
        "* [What is MCP?](/docs/getting-started/intro)\n"
        "##### About MCP.\n"
        "* [Connect to local MCP servers](/docs/develop/connect-local-servers)\n"
        "MCP (Model Context Protocol) is an open-source standard for connecting AI applications.\n"
    )
    out = sanitize_snippet(raw)
    assert "/docs/" not in out
    assert "What is MCP?" in out
    assert "Connect to local MCP servers" in out
    assert "MCP (Model Context Protocol) is an open-source standard" in out


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


def test_deep_research_workflow_target_web_search_calls_is_not_enforced(monkeypatch):
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
                json.dumps(
                    {
                        "tasks": [
                            {"id": "a", "search_query": "q1", "instructions": "i1"},
                            {"id": "b", "search_query": "q2", "instructions": "i2"},
                            {"id": "c", "search_query": "q3", "instructions": "i3"},
                        ]
                    }
                )
            )
        return Resp(
            json.dumps(
                {
                    "title": "REPORT",
                    "summary_bullets": ["a"],
                    "findings": [{"claim": "c", "citations": ["https://example.com/a"]}],
                    "open_questions": [],
                }
            )
        )

    monkeypatch.setattr(common_llm, "completion", fake_completion)

    class OneCallParallelRunner:
        def spawn_parallel(self, tasks, **kwargs):
            return [
                WorkerResult(
                    task_id=t.id,
                    output="x",
                    citations=(f"https://example.com/{t.id}",),
                    web_search_calls=1,
                    success=True,
                )
                for t in tasks
            ]

    wf = DeepResearchWorkflow(
        subagent_runner=FakeSubagentRunner(),  # type: ignore[arg-type]
        parallel_runner=OneCallParallelRunner(),  # type: ignore[arg-type]
        config=DeepResearchConfig(
            model="gpt-4o",
            max_workers=2,
            worker_max_iterations=2,
            worker_timeout_s=10.0,
            target_web_search_calls=2,
            min_total_citations=1,
            min_total_domains=0,
        ),
        emitter=None,
    )

    outcome = wf.run("query")
    assert outcome.report_markdown


def test_deep_research_workflow_deep_profile_round2(monkeypatch):
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
        if "follow-up web searches" in prompt:
            return Resp(
                json.dumps(
                    {
                        "tasks": [
                            {"id": "extra", "search_query": "q4", "instructions": "i4"},
                        ]
                    }
                )
            )
        if "research orchestrator" in prompt:
            return Resp(
                json.dumps(
                    {
                        "tasks": [
                            {"id": "a", "search_query": "q1", "instructions": "i1"},
                            {"id": "b", "search_query": "q2", "instructions": "i2"},
                            {"id": "c", "search_query": "q3", "instructions": "i3"},
                        ]
                    }
                )
            )
        return Resp(
            json.dumps(
                {
                    "title": "REPORT",
                    "summary_bullets": ["a"],
                    "findings": [
                        {"claim": "c1", "citations": ["https://example.com/a"]},
                        {"claim": "c2", "citations": ["https://example.com/r2_extra"]},
                    ],
                    "open_questions": [],
                }
            )
        )

    monkeypatch.setattr(common_llm, "completion", fake_completion)

    class TwoRoundRunner:
        def spawn_parallel(self, tasks, **kwargs):
            return [
                WorkerResult(
                    task_id=t.id,
                    output="x",
                    citations=(f"https://example.com/{t.id}",),
                    web_search_calls=2,
                    success=True,
                )
                for t in tasks
            ]

    wf = DeepResearchWorkflow(
        subagent_runner=FakeSubagentRunner(),  # type: ignore[arg-type]
        parallel_runner=TwoRoundRunner(),  # type: ignore[arg-type]
        config=DeepResearchConfig(
            model="gpt-4o",
            max_workers=2,
            worker_max_iterations=2,
            worker_timeout_s=10.0,
            max_tasks=3,
            enable_round2=True,
            round2_max_tasks=1,
            target_web_search_calls=1,
            min_total_citations=1,
            min_total_domains=0,
        ),
        emitter=None,
    )

    outcome = wf.run("query")
    assert len(outcome.tasks) == 4
    assert any(t.id == "r2_extra" for t in outcome.tasks)


def test_deep_research_workflow_min_domains_enforced(monkeypatch):
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
                json.dumps(
                    {
                        "tasks": [
                            {"id": "a", "search_query": "q1", "instructions": "i1"},
                            {"id": "b", "search_query": "q2", "instructions": "i2"},
                            {"id": "c", "search_query": "q3", "instructions": "i3"},
                        ]
                    }
                )
            )
        return Resp(
            json.dumps(
                {
                    "title": "REPORT",
                    "summary_bullets": ["a"],
                    "findings": [{"claim": "c", "citations": ["https://example.com/a"]}],
                    "open_questions": [],
                }
            )
        )

    monkeypatch.setattr(common_llm, "completion", fake_completion)

    class SameDomainRunner:
        def spawn_parallel(self, tasks, **kwargs):
            return [
                WorkerResult(
                    task_id=t.id,
                    output="x",
                    citations=("https://example.com/same",),
                    web_search_calls=1,
                    success=True,
                )
                for t in tasks
            ]

    wf = DeepResearchWorkflow(
        subagent_runner=FakeSubagentRunner(),  # type: ignore[arg-type]
        parallel_runner=SameDomainRunner(),  # type: ignore[arg-type]
        config=DeepResearchConfig(
            model="gpt-4o",
            max_workers=2,
            worker_max_iterations=2,
            worker_timeout_s=10.0,
            min_total_citations=1,
            min_total_domains=2,
        ),
        emitter=None,
    )

    with pytest.raises(RuntimeError):
        wf.run("query")
