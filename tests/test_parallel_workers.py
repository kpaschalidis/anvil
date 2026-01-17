import json
from pathlib import Path

from anvil.subagents.parallel import ParallelWorkerRunner, WorkerTask
from anvil.subagents.registry import AgentRegistry
from anvil.subagents.task_tool import SubagentRunner
from anvil.tools import ToolRegistry


class _ToolCallFn:
    def __init__(self, name: str, arguments: str):
        self.name = name
        self.arguments = arguments


class _ToolCall:
    def __init__(self, tool_call_id: str, name: str, arguments: str):
        self.id = tool_call_id
        self.function = _ToolCallFn(name, arguments)


class _Msg:
    def __init__(self, content: str | None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class _Choice:
    def __init__(self, msg: _Msg):
        self.message = msg


class _Resp:
    def __init__(self, msg: _Msg):
        self.choices = [_Choice(msg)]


def test_subagent_runner_blocks_disallowed_tool_execution(tmp_path: Path):
    calls: list[str] = []

    tools = ToolRegistry()

    def write_file(filepath: str, content: str) -> str:
        calls.append("write_file")
        return "ok"

    tools.register_tool(
        name="write_file",
        description="write",
        parameters={
            "type": "object",
            "properties": {"filepath": {"type": "string"}, "content": {"type": "string"}},
            "required": ["filepath", "content"],
        },
        implementation=write_file,
    )

    state = {"n": 0}

    def fake_completion(**kwargs):
        state["n"] += 1
        if state["n"] == 1:
            return _Resp(
                _Msg(
                    content="",
                    tool_calls=[
                        _ToolCall(
                            "tc1",
                            "write_file",
                            json.dumps({"filepath": "x.txt", "content": "nope"}),
                        )
                    ],
                )
            )
        return _Resp(_Msg("done", tool_calls=None))

    runner = SubagentRunner(
        root_path=tmp_path,
        agent_registry=AgentRegistry(tmp_path),
        tool_registry=tools,
        vendored_prompts={"agent_prompts": {"task": "", "explore": ""}},
        completion_fn=fake_completion,
        default_model="gpt-4o",
    )

    out = runner.run_task("hi", allowed_tool_names={"read_file"})
    assert out == "done"
    assert calls == []


def test_parallel_worker_runner_passes_restricted_tools_by_default():
    class FakeRunner:
        def __init__(self):
            self.allowed: list[object] = []

        def run_task(self, *, prompt, agent_name=None, max_iterations=6, allowed_tool_names=None, model=None):
            self.allowed.append(allowed_tool_names)
            if prompt == "boom":
                raise RuntimeError("fail")
            return f"ok:{prompt}"

    runner = FakeRunner()
    pw = ParallelWorkerRunner(runner)  # type: ignore[arg-type]
    results = pw.spawn_parallel(
        [
            WorkerTask(id="a", prompt="one"),
            WorkerTask(id="b", prompt="boom"),
        ],
        max_workers=2,
        timeout=5.0,
        allow_writes=False,
    )

    assert len(results) == 2
    assert {r.task_id for r in results} == {"a", "b"}
    assert any(r.task_id == "a" and r.success and r.output == "ok:one" for r in results)
    assert any(r.task_id == "b" and (not r.success) and r.error for r in results)

    assert runner.allowed[0] is not None
    assert runner.allowed[1] is not None

    results2 = pw.spawn_parallel([WorkerTask(id="c", prompt="two")], allow_writes=True)
    assert results2[0].success
    assert runner.allowed[-1] is None

