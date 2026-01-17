from __future__ import annotations

from anvil.config import AgentConfig
from anvil.runtime.repl import AnvilREPL
from anvil.runtime.runtime import AnvilRuntime
from anvil.subagents.parallel import ParallelWorkerRunner
from anvil.workflows.deep_research import DeepResearchConfig, DeepResearchWorkflow


class AnvilAgent:
    """Facade over AnvilRuntime for interactive mode."""

    def __init__(self, root_path: str, config: AgentConfig | None = None, *, mode=None):
        self.runtime = AnvilRuntime(root_path, config, mode=mode)
        self._register_workflow_tools()

    def _register_workflow_tools(self) -> None:
        self.runtime.tools.register_tool(
            name="need_finding",
            description="Research pain points: fetch docs, extract insights, analyze, report",
            parameters={
                "type": "object",
                "properties": {"topic": {"type": "string"}},
                "required": ["topic"],
            },
            implementation=self._tool_need_finding,
        )
        self.runtime.tools.register_tool(
            name="deep_research",
            description="Deep research with parallel search agents",
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
            implementation=self._tool_deep_research,
        )

    def _tool_need_finding(self, topic: str, sources: list[str] | None = None) -> str:
        return f"need_finding for '{topic}' not implemented yet. Use `anvil fetch` for now."

    def _tool_deep_research(self, query: str) -> str:
        workflow = DeepResearchWorkflow(
            subagent_runner=self.runtime.subagent_runner,
            parallel_runner=ParallelWorkerRunner(self.runtime.subagent_runner),
            config=DeepResearchConfig(model=self.runtime.config.model),
            emitter=None,
        )
        return workflow.run(query)

    def run_interactive(self, *, initial_message: str | None = None) -> None:
        repl = AnvilREPL(self.runtime)
        repl.run(initial_message=initial_message)

    def execute(self, prompt: str, *, files: list[str] | None = None) -> str:
        return self.runtime.run_prompt(prompt, files=files)
