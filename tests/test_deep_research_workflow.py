import json

import pytest

from anvil.workflows.deep_research import (
    DeepResearchConfig,
    DeepResearchRunError,
    DeepResearchWorkflow,
    PlanningError,
)
from anvil.workflows.deep_research import _select_diverse_findings, sanitize_snippet
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


def test_deep_research_worker_continuation_respects_extract_cap(monkeypatch):
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
                            {"id": "task1", "search_query": "q1", "instructions": "i1"},
                            {"id": "task2", "search_query": "q2", "instructions": "i2"},
                            {"id": "task3", "search_query": "q3", "instructions": "i3"},
                        ]
                    }
                )
            )
        if "research synthesizer" in prompt:
            return Resp(
                json.dumps(
                    {
                        "title": "REPORT",
                        "summary_bullets": ["a"],
                        "findings": [
                            {
                                "claim": "c",
                                "citations": ["https://example.com/a1"],
                                "why": "because",
                            }
                        ],
                        "open_questions": [],
                    }
                )
            )
        return Resp("{}")

    monkeypatch.setattr(common_llm, "completion", fake_completion)

    class CapturingParallelRunner:
        def __init__(self):
            self.calls: list[dict] = []

        def spawn_parallel(self, tasks, **kwargs):
            self.calls.append({"tasks": tasks, "kwargs": kwargs})
            # first call: return a deep-read worker with full extract cap already used
            if len(self.calls) == 1:
                out = []
                for t in tasks:
                    if t.id == "task1":
                        out.append(
                            WorkerResult(
                                task_id=t.id,
                                output="note",
                                citations=("https://example.com/a1", "https://example.com/a2"),
                                web_search_calls=1,
                                web_extract_calls=3,
                                evidence=(
                                    {"url": "https://example.com/a1", "raw_len": 100},
                                    {"url": "https://example.com/a2", "raw_len": 100},
                                    {"url": "https://example.com/a3", "raw_len": 100},
                                ),
                                success=True,
                            )
                        )
                    else:
                        out.append(
                            WorkerResult(
                                task_id=t.id,
                                output="note",
                                citations=(f"https://example.com/{t.id}",),
                                web_search_calls=4,
                                web_extract_calls=0,
                                evidence=(),
                                success=True,
                            )
                        )
                return out

            # continuation call: ensure no remaining extract budget is passed to task1
            assert len(tasks) == 1
            assert tasks[0].id == "task1"
            assert int(tasks[0].max_web_extract_calls or 0) == 0
            assert int(kwargs.get("max_web_extract_calls") or 0) == 3
            return [
                WorkerResult(
                    task_id="task1",
                    output="more",
                    citations=("https://example.com/a4",),
                    web_search_calls=3,
                    web_extract_calls=0,
                    evidence=(),
                    success=True,
                )
            ]

    runner = CapturingParallelRunner()
    wf = DeepResearchWorkflow(
        subagent_runner=FakeSubagentRunner(),  # type: ignore[arg-type]
        parallel_runner=runner,  # type: ignore[arg-type]
        config=DeepResearchConfig(
            model="gpt-4o",
            max_workers=2,
            worker_max_iterations=2,
            worker_timeout_s=10.0,
            enable_deep_read=True,
            max_web_extract_calls=3,
            enable_worker_continuation=True,
            max_worker_continuations=1,
            target_web_search_calls=4,
            max_web_search_calls=8,
            require_citations=False,
            strict_all=False,
            min_total_domains=0,
        ),
        emitter=None,
    )
    outcome = wf.run("query")
    merged = {r.task_id: r for r in outcome.results}
    assert merged["task1"].web_extract_calls == 3


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


def test_sanitize_snippet_removes_inline_headings_and_bullets():
    raw = (
        "What is MCP?. ##### About MCP. ##### Develop with MCP. * Connect to local MCP servers. "
        "* Connect to remote MCP Servers. MCP is an open-source standard."
    )
    out = sanitize_snippet(raw)
    assert "#####" not in out
    assert " * " not in out


def test_select_diverse_findings_prefers_new_urls_and_domains():
    candidates = [
        {
            "claim": "a",
            "evidence": [
                {"url": "https://a.com/1", "quote": "q"},
                {"url": "https://a.com/2", "quote": "q"},
            ],
        },
        {
            "claim": "b",
            "evidence": [
                {"url": "https://b.com/1", "quote": "q"},
                {"url": "https://c.com/1", "quote": "q"},
            ],
        },
        {
            "claim": "c",
            "evidence": [
                {"url": "https://a.com/1", "quote": "q"},
                {"url": "https://d.com/1", "quote": "q"},
            ],
        },
    ]
    out = _select_diverse_findings(
        candidates,
        target_findings=2,
        min_unique_urls_target=0,
        min_unique_domains_target=0,
    )
    assert len(out) == 2
    urls = {e["url"] for f in out for e in (f.get("evidence") or []) if isinstance(e, dict)}
    domains = {u.split("/")[2] for u in urls}
    # Expect at least 2 domains covered with two findings.
    assert len(domains) >= 2


def test_deep_multi_pass_section_writer_retries_on_truncated_json(monkeypatch):
    from common import llm as common_llm

    calls = {"n": 0}

    def fake_completion(**kwargs):
        calls["n"] += 1

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
        # planning
        if "research orchestrator" in prompt and '"tasks"' in prompt:
            return Resp(
                json.dumps(
                    {
                        "tasks": [
                            {"id": "task1", "search_query": "q1", "instructions": "i1"},
                            {"id": "task2", "search_query": "q2", "instructions": "i2"},
                            {"id": "task3", "search_query": "q3", "instructions": "i3"},
                        ]
                    }
                )
            )
        # outline
        if "research outline planner" in prompt:
            return Resp(
                json.dumps(
                    {"sections": [{"id": "s1", "title": "Section", "task_ids": ["task1", "task2"]}]}
                )
            )
        # section writer: first call returns truncated fenced json; second call returns valid raw json
        if "research writer for one section" in prompt:
            # retry call includes assistant message; detect by messages length
            if len(kwargs.get("messages") or []) >= 3:
                return Resp(
                    json.dumps(
                        {
                            "findings": [
                                {
                                    "claim": "c",
                                    "evidence": [
                                        {"url": "https://example.com/a", "quote": "QUOTE"},
                                    ],
                                }
                            ]
                        }
                    )
                )
            return Resp("```json\n{\"findings\": [{\"claim\": \"c\"")  # intentionally cut off
        # summary
        if "research summarizer" in prompt:
            return Resp(
                json.dumps(
                    {
                        "title": "REPORT",
                        "summary_bullets": ["a"],
                        "open_questions": [],
                    }
                )
            )
        return Resp("{}")

    monkeypatch.setattr(common_llm, "completion", fake_completion)

    class EvidenceRunner:
        def spawn_parallel(self, tasks, **kwargs):
            # Provide evidence excerpts that contain the quote substring.
            return [
                WorkerResult(
                    task_id=t.id,
                    output="x",
                    citations=("https://example.com/a",),
                    sources={"https://example.com/a": {"title": "t", "snippet": "s"}},
                    web_search_calls=2,
                    web_search_trace=(
                        {"success": True, "results": [{"url": "https://example.com/a", "title": "t", "score": 0.9, "snippet": "s"}]},
                    ),
                    web_extract_calls=1,
                    evidence=(
                        {"url": "https://example.com/a", "title": "t", "excerpt": "xx QUOTE yy"},
                    ),
                    success=True,
                )
                for t in tasks
            ]

    wf = DeepResearchWorkflow(
        subagent_runner=FakeSubagentRunner(),  # type: ignore[arg-type]
        parallel_runner=EvidenceRunner(),  # type: ignore[arg-type]
        config=DeepResearchConfig(
            model="gpt-4o",
            max_workers=1,
            worker_max_iterations=1,
            worker_timeout_s=10.0,
            enable_deep_read=True,
            max_web_extract_calls=1,
            require_quote_per_claim=True,
            multi_pass_synthesis=True,
            enable_round2=False,
            verify_max_tasks=0,
            min_total_domains=0,
            min_total_citations=1,
            report_min_unique_citations_target=1,
            report_min_unique_domains_target=1,
            report_findings_target=1,
        ),
        emitter=None,
    )
    outcome = wf.run("query")
    assert outcome.report_markdown.startswith("# REPORT")
    assert calls["n"] >= 4  # plan + outline + section (+retry) + summary


def test_deep_research_wraps_provider_errors_as_run_error(monkeypatch):
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
        if "research orchestrator" in prompt and '"tasks"' in prompt:
            return Resp(
                json.dumps(
                    {
                        "tasks": [
                            {"id": "task1", "search_query": "q1", "instructions": "i1"},
                            {"id": "task2", "search_query": "q2", "instructions": "i2"},
                            {"id": "task3", "search_query": "q3", "instructions": "i3"},
                        ]
                    }
                )
            )
        if "research outline planner" in prompt:
            raise RuntimeError("ContextWindowExceededError: too many tokens")
        return Resp("{}")

    monkeypatch.setattr(common_llm, "completion", fake_completion)

    class EvidenceRunner:
        def spawn_parallel(self, tasks, **kwargs):
            return [
                WorkerResult(
                    task_id=t.id,
                    output="x",
                    citations=("https://example.com/a",),
                    web_search_calls=2,
                    web_extract_calls=1,
                    evidence=(
                        {"url": "https://example.com/a", "title": "t", "excerpt": "xx QUOTE yy"},
                    ),
                    success=True,
                )
                for t in tasks
            ]

    wf = DeepResearchWorkflow(
        subagent_runner=FakeSubagentRunner(),  # type: ignore[arg-type]
        parallel_runner=EvidenceRunner(),  # type: ignore[arg-type]
        config=DeepResearchConfig(
            model="gpt-4o",
            max_workers=1,
            worker_max_iterations=1,
            worker_timeout_s=10.0,
            enable_deep_read=True,
            max_web_extract_calls=1,
            require_quote_per_claim=True,
            multi_pass_synthesis=True,
            enable_round2=False,
            verify_max_tasks=0,
            min_total_domains=0,
            min_total_citations=1,
        ),
        emitter=None,
    )
    with pytest.raises(DeepResearchRunError) as e:
        wf.run("query")
    assert e.value.outcome is not None
    assert len(e.value.outcome.results) == 3


def test_quick_synthesis_repairs_for_coverage(monkeypatch):
    from common import llm as common_llm

    calls = {"n": 0}

    def fake_completion(**kwargs):
        calls["n"] += 1

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

        # Repair attempt is indicated by our explicit message.
        if kwargs["messages"][-1]["role"] == "user" and "did not meet requirements" in kwargs["messages"][-1]["content"]:
            return Resp(
                json.dumps(
                    {
                        "title": "REPORT",
                        "summary_bullets": ["a"],
                        "findings": [
                            {"claim": "c1", "citations": ["https://example.com/a", "https://example.com/b"]},
                            {"claim": "c2", "citations": ["https://example.com/b", "https://example.com/c"]},
                            {"claim": "c3", "citations": ["https://example.com/c", "https://example.com/a"]},
                        ],
                        "open_questions": [],
                    }
                )
            )

        # First synthesis: valid JSON but too few unique citations.
        return Resp(
            json.dumps(
                {
                    "title": "REPORT",
                    "summary_bullets": ["a"],
                    "findings": [
                        {"claim": "c1", "citations": ["https://example.com/a"]},
                        {"claim": "c2", "citations": ["https://example.com/a"]},
                        {"claim": "c3", "citations": ["https://example.com/a"]},
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
            min_total_citations=1,
            report_min_unique_citations_target=3,
            report_min_unique_domains_target=1,
            report_findings_target=3,
        ),
        emitter=None,
    )
    outcome = wf.run("query")
    assert outcome.report_markdown.startswith("# REPORT")
    assert calls["n"] >= 3  # planning + synthesis + repair


def test_quick_synthesis_hard_fails_on_unrepairable_grounding(monkeypatch):
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
        # Synthesis always returns a non-allowed citation.
        return Resp(
            json.dumps(
                {
                    "title": "REPORT",
                    "summary_bullets": ["a"],
                    "findings": [{"claim": "c", "citations": ["https://bad.com/x"]}],
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
            min_total_citations=1,
            report_min_unique_citations_target=1,
            report_min_unique_domains_target=1,
            report_findings_target=1,
        ),
        emitter=None,
    )
    with pytest.raises(DeepResearchRunError):
        wf.run("query")


def test_quick_curated_source_pack_respects_max_total(monkeypatch):
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
        # Synthesis: cite the top result for each task (unique domains).
        return Resp(
            json.dumps(
                {
                    "title": "REPORT",
                    "summary_bullets": ["a"],
                    "findings": [
                        {
                            "claim": "c1",
                            "citations": ["https://a.example.com/1", "https://b.example.com/1"],
                        },
                        {
                            "claim": "c2",
                            "citations": ["https://c.example.com/1", "https://a.example.com/1"],
                        },
                    ],
                    "open_questions": [],
                }
            )
        )

    monkeypatch.setattr(common_llm, "completion", fake_completion)

    class RankedRunner:
        def spawn_parallel(self, tasks, **kwargs):
            results = []
            for t in tasks:
                url1 = f"https://{t.id}.example.com/1"
                url2 = f"https://{t.id}.example.com/2"
                results.append(
                    WorkerResult(
                        task_id=t.id,
                        output="x",
                        citations=(url1, url2),
                        sources={
                            url1: {"title": f"{t.id}1", "snippet": "s1"},
                            url2: {"title": f"{t.id}2", "snippet": "s2"},
                        },
                        web_search_calls=1,
                        web_search_trace=(
                            {
                                "success": True,
                                "results": [
                                    {"url": url1, "title": f"{t.id}1", "score": 0.9, "snippet": "s1"},
                                    {"url": url2, "title": f"{t.id}2", "score": 0.8, "snippet": "s2"},
                                ],
                            },
                        ),
                        success=True,
                    )
                )
            return results

    wf = DeepResearchWorkflow(
        subagent_runner=FakeSubagentRunner(),  # type: ignore[arg-type]
        parallel_runner=RankedRunner(),  # type: ignore[arg-type]
        config=DeepResearchConfig(
            model="gpt-4o",
            max_workers=2,
            worker_max_iterations=2,
            worker_timeout_s=10.0,
            min_total_domains=0,
            min_total_citations=1,
            curated_sources_max_total=3,
            curated_sources_max_per_domain=1,
            curated_sources_min_per_task=1,
            report_min_unique_citations_target=1,
            report_min_unique_domains_target=1,
            report_findings_target=2,
        ),
        emitter=None,
    )
    outcome = wf.run("query")
    assert isinstance(outcome.synthesis_input, dict)
    curated = outcome.synthesis_input.get("curated_sources")
    assert isinstance(curated, list)
    assert len(curated) <= 3


def test_synthesis_prompt_includes_allowed_url_list(monkeypatch):
    from common import llm as common_llm

    seen_prompt = {"text": ""}

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
        seen_prompt["text"] = prompt
        return Resp(
            json.dumps(
                {
                    "title": "REPORT",
                    "summary_bullets": ["a"],
                    "findings": [
                        {"claim": "c", "citations": ["https://example.com/a"]},
                    ],
                    "open_questions": [],
                }
            )
        )

    monkeypatch.setattr(common_llm, "completion", fake_completion)

    class OneUrlRunner:
        def spawn_parallel(self, tasks, **kwargs):
            return [
                WorkerResult(
                    task_id=t.id,
                    output="x",
                    citations=("https://example.com/a",),
                    sources={"https://example.com/a": {"title": "t", "snippet": "s"}},
                    web_search_calls=1,
                    web_search_trace=(
                        {
                            "success": True,
                            "results": [{"url": "https://example.com/a", "title": "t", "score": 0.9, "snippet": "s"}],
                        },
                    ),
                    success=True,
                )
                for t in tasks
            ]

    wf = DeepResearchWorkflow(
        subagent_runner=FakeSubagentRunner(),  # type: ignore[arg-type]
        parallel_runner=OneUrlRunner(),  # type: ignore[arg-type]
        config=DeepResearchConfig(
            model="gpt-4o",
            max_workers=1,
            worker_max_iterations=1,
            worker_timeout_s=10.0,
            min_total_domains=0,
            min_total_citations=1,
            curated_sources_max_total=1,
            curated_sources_max_per_domain=1,
            curated_sources_min_per_task=1,
            report_min_unique_citations_target=1,
            report_min_unique_domains_target=1,
            report_findings_target=1,
        ),
        emitter=None,
    )
    wf.run("query")
    assert "Allowed citation URLs" in seen_prompt["text"]
    assert "https://example.com/a" in seen_prompt["text"]


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
