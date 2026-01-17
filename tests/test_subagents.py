from pathlib import Path

from anvil.history import MessageHistory
from anvil.subagents.registry import AgentRegistry
from anvil.subagents.task_tool import SubagentRunner, TaskTool
from anvil.tools import ToolRegistry


class _FakeMessage:
    def __init__(self, content: str):
        self.content = content
        self.tool_calls = None


class _FakeChoice:
    def __init__(self, content: str):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content: str):
        self.choices = [_FakeChoice(content)]


def _fake_completion(**kwargs):
    return _FakeResponse("done")


def test_agent_registry_loads(tmp_path: Path):
    agents_dir = tmp_path / ".anvil" / "agents"
    agents_dir.mkdir(parents=True)
    agent_file = agents_dir / "helper.md"
    agent_file.write_text(
        "---\nname: helper\ndescription: test agent\n---\nYou help.\n",
        encoding="utf-8",
    )

    registry = AgentRegistry(tmp_path)
    registry.reload()

    assert "helper" in registry.agents
    assert registry.agents["helper"].description == "test agent"


def test_task_tool_returns_output_and_isolated_history(tmp_path: Path):
    registry = AgentRegistry(tmp_path)
    registry.reload()
    tools = ToolRegistry()
    runner = SubagentRunner(
        root_path=tmp_path,
        agent_registry=registry,
        tool_registry=tools,
        vendored_prompts={"agent_prompts": {"task": "", "explore": ""}},
        completion_fn=_fake_completion,
        default_model="gpt-4o",
    )
    task_tool = TaskTool(runner)

    history = MessageHistory()
    history.add_user_message("main")

    output = task_tool(prompt="do work")

    assert output == "done"
    assert history.messages == [{"role": "user", "content": "main"}]
