import json

from anvil.subagents.parallel import WorkerResult
from anvil.workflows.deep_research import DeepResearchConfig, DeepResearchWorkflow
from anvil.workflows.deep_research_resume import resume_deep_research


class FakeParallelRunner:
    def __init__(self):
        self.calls = 0

    def spawn_parallel(self, tasks, **kwargs):
        self.calls += 1
        out = []
        for t in tasks:
            out.append(
                WorkerResult(
                    task_id=t.id,
                    output=f"- found for {t.id}: https://example.com/{t.id}",
                    citations=(f"https://example.com/{t.id}",),
                    web_search_calls=1,
                    success=True,
                )
            )
        return out


class FakeSubagentRunner:
    def run_task(self, **kwargs):
        return "unused"


def test_resume_deep_research_reruns_failed_workers(tmp_path, monkeypatch):
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

        return Resp(
            json.dumps(
                {
                    "title": "REPORT",
                    "summary_bullets": ["a"],
                    "findings": [
                        {"claim": "c1", "citations": ["https://example.com/a"]},
                        {"claim": "c2", "citations": ["https://example.com/b"]},
                    ],
                    "open_questions": [],
                }
            )
        )

    monkeypatch.setattr(common_llm, "completion", fake_completion)

    session_id = "abc12345"
    session_dir = tmp_path / session_id / "research"
    workers_dir = session_dir / "workers"
    workers_dir.mkdir(parents=True)

    (session_dir / "plan.json").write_text(
        json.dumps(
            {
                "tasks": [
                    {"id": "a", "search_query": "q1", "instructions": "i1"},
                    {"id": "b", "search_query": "q2", "instructions": "i2"},
                ]
            }
        ),
        encoding="utf-8",
    )

    (workers_dir / "a.json").write_text(
        json.dumps(
            {
                "task_id": "a",
                "success": True,
                "web_search_calls": 1,
                "citations": ["https://example.com/a"],
                "output": "ok",
            }
        ),
        encoding="utf-8",
    )

    pr = FakeParallelRunner()
    wf = DeepResearchWorkflow(
        subagent_runner=FakeSubagentRunner(),  # type: ignore[arg-type]
        parallel_runner=pr,  # type: ignore[arg-type]
        config=DeepResearchConfig(model="gpt-4o", max_workers=2, worker_max_iterations=2, worker_timeout_s=10.0),
        emitter=None,
    )

    outcome = resume_deep_research(
        workflow=wf,
        data_dir=str(tmp_path),
        session_id=session_id,
        query="query",
        max_attempts=2,
    )

    assert pr.calls == 1
    assert outcome.report_markdown.startswith("# REPORT")
    assert "https://example.com/a" in outcome.report_markdown
    assert "https://example.com/b" in outcome.report_markdown

