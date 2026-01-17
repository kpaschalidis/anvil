import json

from anvil.workflows.deep_research import DeepResearchConfig, DeepResearchWorkflow
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
        if "Return ONLY valid JSON" in prompt:
            return Resp("not json")
        return Resp("REPORT")

    monkeypatch.setattr(common_llm, "completion", fake_completion)

    wf = DeepResearchWorkflow(
        subagent_runner=FakeSubagentRunner(),  # type: ignore[arg-type]
        parallel_runner=FakeParallelRunner(),  # type: ignore[arg-type]
        config=DeepResearchConfig(model="gpt-4o", max_workers=2, worker_max_iterations=2, worker_timeout_s=10.0),
        emitter=None,
    )
    out = wf.run("query")
    assert out.startswith("REPORT")
    assert "## Sources" in out
