import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List

from common import llm
from common.agent_loop import LoopConfig, run_loop
from common.events import (
    AssistantDeltaEvent,
    AssistantMessageEvent,
    AssistantResponseStartEvent,
    EventEmitter,
    ToolCallEvent,
    ToolResultEvent,
)
from anvil.config import AgentConfig, resolve_model_alias
from anvil.files import FileManager
from anvil.history import MessageHistory
from anvil.shell import ShellRunner
from anvil.tools import ToolRegistry
from anvil.prompts import build_main_system_prompt, load_prompt_blocks
from anvil.ext.markdown_executor import MarkdownExecutor
from anvil.ext.markdown_loader import MarkdownIndex
from anvil.sessions.manager import SessionManager
from anvil.subagents.registry import AgentRegistry
from anvil.subagents.task_tool import SubagentRunner, TaskTool
from anvil.modes.base import ModeConfig
from anvil.runtime.hooks import RuntimeHooks
from anvil.tools.extract import WEB_EXTRACT_TOOL_SCHEMA, web_extract
from anvil.tools.search import WEB_SEARCH_TOOL_SCHEMA, web_search


class AnvilRuntime:
    def __init__(
        self,
        root_path: str,
        config: AgentConfig | None = None,
        mode: ModeConfig | None = None,
    ):
        self.root_path = Path(root_path)
        self.mode = mode

        if mode and mode.apply_defaults:
            config = mode.apply_defaults(config or AgentConfig())

        self.config = config or AgentConfig()

        self.history = MessageHistory()
        self.files = FileManager(str(root_path))
        self.shell = ShellRunner(str(root_path))
        self.tools = ToolRegistry()

        self.files_in_context: List[str] = []
        self.interrupted = False
        self.hooks = RuntimeHooks()
        self.extensions: dict[str, Any] = {}

        self.markdown_index = MarkdownIndex(self.root_path)
        self.markdown_index.reload()
        self.markdown_executor = MarkdownExecutor(
            self.root_path, self.history, self._send_to_llm_with_tools
        )

        self.agent_registry = AgentRegistry(self.root_path)
        self.agent_registry.reload()

        core_blocks = Path(__file__).resolve().parents[1] / "prompts" / "blocks"
        prompt_block_dirs = (mode.prompt_block_dirs if mode else []) + [core_blocks]
        self.vendored_prompts = load_prompt_blocks(prompt_block_dirs=prompt_block_dirs)

        self.session_namespace = mode.session_namespace if mode else "default"

        self._register_tools()
        if mode and mode.register_tools:
            mode.register_tools(self.tools, self)
        self.subagent_runner = SubagentRunner(
            root_path=self.root_path,
            agent_registry=self.agent_registry,
            tool_registry=self.tools,
            vendored_prompts=self.vendored_prompts,
            completion_fn=llm.completion,
            default_model=self.config.model,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
        )
        self._register_subagent_tools()
        self.system_prompt_version = "anvil-1"
        self._set_system_prompt()
        self.session_manager = SessionManager(
            self.root_path,
            namespace=self.session_namespace,
            model=self.config.model,
            system_prompt_hash=self.system_prompt_hash,
            system_prompt_version=self.system_prompt_version,
        )

    def reload_extensions(self) -> None:
        self.markdown_index.reload()
        self.agent_registry.reload()

    def _register_tools(self):
        self.tools.register_tool(
            name="read_file",
            description="Read the contents of a file from the repository",
            parameters={
                "type": "object",
                "properties": {
                    "filepath": {
                        "type": "string",
                        "description": "Path to the file relative to repository root",
                    }
                },
                "required": ["filepath"],
            },
            implementation=self._tool_read_file,
        )

        self.tools.register_tool(
            name="write_file",
            description="Write content to a file (creates or overwrites)",
            parameters={
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "Path to the file"},
                    "content": {
                        "type": "string",
                        "description": "Content to write to the file",
                    },
                },
                "required": ["filepath", "content"],
            },
            implementation=self._tool_write_file,
        )

        self.tools.register_tool(
            name="list_files",
            description="List files in the repository matching a pattern",
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Glob pattern to match files (e.g., '*.py', 'src/**/*.js')",
                        "default": "*",
                    }
                },
                "required": [],
            },
            implementation=self._tool_list_files,
        )

        self.tools.register_tool(
            name="grep",
            description="Search for patterns in files using ripgrep",
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regex pattern to search"},
                    "path": {
                        "type": "string",
                        "description": "File or directory to search",
                        "default": ".",
                    },
                    "include": {
                        "type": "string",
                        "description": "Glob pattern for files to include (e.g. '*.py')",
                    },
                },
                "required": ["pattern"],
            },
            implementation=self._tool_grep,
        )

        self.tools.register_tool(
            name="run_command",
            description="Execute a shell command in the repository",
            parameters={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to execute",
                    }
                },
                "required": ["command"],
            },
            implementation=self._tool_run_command,
        )

        self.tools.register_tool(
            name="web_search",
            description="Search the web (Tavily)",
            parameters=WEB_SEARCH_TOOL_SCHEMA,
            implementation=self._tool_web_search,
        )

        self.tools.register_tool(
            name="web_extract",
            description="Extract raw page content (Tavily)",
            parameters=WEB_EXTRACT_TOOL_SCHEMA,
            implementation=self._tool_web_extract,
        )

        self.tools.register_tool(
            name="skill",
            description="Load a skill's instructions into context",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Name of the skill to load"},
                },
                "required": ["name"],
            },
            implementation=self._tool_skill,
        )

    def _register_subagent_tools(self) -> None:
        task_tool = TaskTool(self.subagent_runner)
        self.tools.register_tool(
            name="task",
            description="Run a subagent task with the full toolset",
            parameters={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Task instructions"},
                    "agent": {
                        "type": "string",
                        "description": "Optional subagent name",
                    },
                    "subagent_type": {
                        "type": "string",
                        "description": "Alias for agent name",
                    },
                },
                "required": ["prompt"],
            },
            implementation=task_tool,
        )

    def _tool_read_file(self, filepath: str) -> str:
        return self.files.read_file(filepath)

    def _tool_write_file(self, filepath: str, content: str) -> str:
        self.files.write_file(filepath, content)
        self.hooks.fire_files_changed([filepath], "write_file")
        return f"File {filepath} written successfully"

    def _tool_list_files(self, pattern: str = "*") -> str:
        files = self.files.list_files(pattern)
        return "\n".join(files) if files else "No files found"

    def _tool_grep(
        self, pattern: str, path: str = ".", include: str | None = None
    ) -> str:
        base_path = str(self.root_path / path)
        use_rg = shutil.which("rg") is not None
        if use_rg:
            cmd = ["rg", "-n", "--no-heading"]
            if include:
                cmd.extend(["--glob", include])
            cmd.extend([pattern, base_path])
        else:
            cmd = ["grep", "-R", "-n"]
            if include:
                cmd.extend(["--include", include])
            cmd.extend([pattern, base_path])

        result = subprocess.run(
            cmd,
            cwd=self.root_path,
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            return result.stdout
        if result.returncode == 1:
            return "No matches"
        return result.stderr or "Search failed"

    def _tool_run_command(self, command: str) -> str:
        result = self.shell.run_command(command)

        if result["success"]:
            return f"Exit code: {result['exit_code']}\n\nOutput:\n{result['stdout']}"
        error = result.get("error", result.get("stderr", "Unknown error"))
        return f"Command failed: {error}"

    def _tool_skill(self, name: str) -> str:
        entry = self.markdown_index.skills.get(name)
        if not entry:
            return f"Skill not found: {name}"
        return entry.body

    def _tool_web_search(
        self,
        query: str,
        page: int = 1,
        page_size: int = 5,
        max_results: int | None = None,
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
        days: int | None = None,
        include_raw_content: bool = False,
    ) -> dict[str, Any]:
        return web_search(
            query=query,
            page=page,
            page_size=page_size,
            max_results=max_results,
            include_domains=include_domains,
            exclude_domains=exclude_domains,
            days=days,
            include_raw_content=include_raw_content,
        )

    def _tool_web_extract(self, url: str, max_chars: int = 20_000) -> dict[str, Any]:
        return web_extract(url=url, max_chars=max_chars)

    def run_turn(self, message: str | None = None) -> None:
        if message:
            self.history.add_user_message(message)
        self._send_to_llm_with_tools()

    def _set_system_prompt(self):
        memory_path = self.root_path / "ANVIL.md"
        memory_text = memory_path.read_text(encoding="utf-8") if memory_path.exists() else None
        tool_names = [tool["function"]["name"] for tool in self.tools.get_tool_schemas()]
        system_prompt = build_main_system_prompt(
            root_path=self.root_path,
            tool_names=tool_names,
            memory_text=memory_text,
            vendored_blocks=self.vendored_prompts,
        )
        self.history.set_system_prompt(system_prompt)
        self.system_prompt_hash = hashlib.sha256(
            system_prompt.encode("utf-8")
        ).hexdigest()
        if hasattr(self, "session_manager"):
            self.session_manager.system_prompt_hash = self.system_prompt_hash
            self.session_manager.system_prompt_version = self.system_prompt_version

    def add_file_to_context(self, filepath: str):
        if filepath not in self.files_in_context:
            self.files_in_context.append(filepath)

            try:
                content = self.files.read_file(filepath)
                context_msg = f"=== {filepath} ===\n{content}\n"
                self.history.add_user_message(context_msg)
                print(f"✅ Added {filepath} to context")
            except Exception as e:
                print(f"❌ Error adding {filepath}: {e}")

    def process_user_message(self, message: str):
        self.history.add_user_message(message)
        self._send_to_llm_with_tools()

    def run_prompt(
        self,
        prompt: str,
        *,
        files: list[str] | None = None,
        max_iterations: int = 10,
    ) -> str:
        if files:
            for filepath in files:
                self.add_file_to_context(filepath)
        self.history.add_user_message(prompt)
        result = run_loop(
            messages=self.history.messages,
            tools=self.tools.get_tool_schemas(),
            execute_tool=lambda name, args: self.tools.execute_tool(name, args),
            config=LoopConfig(
                model=resolve_model_alias(self.config.model),
                system_prompt=self.history.system_prompt,
                max_iterations=max_iterations,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
                stream=False,
                use_tools=self.config.use_tools,
            ),
            emitter=None,
        )
        self.hooks.fire_turn_end()
        return result.final_response

    def _send_to_llm_with_tools(self):
        self._send_to_llm_with_tools_internal()
        self.hooks.fire_turn_end()

    def _send_to_llm_with_tools_internal(self):
        started_response = False

        def on_event(event) -> None:
            nonlocal started_response

            if isinstance(event, AssistantResponseStartEvent):
                started_response = False
                return
            if isinstance(event, AssistantDeltaEvent):
                if not started_response:
                    print("\n🤖 Assistant:", end=" ")
                    started_response = True
                print(event.text, end="", flush=True)
                return
            if isinstance(event, AssistantMessageEvent):
                if self.config.stream and started_response:
                    print()
                if event.content:
                    self.hooks.fire_assistant_message(event.content)
                    self._autosave()
                return
            if isinstance(event, ToolCallEvent):
                print(f"\n🔧 Calling: {event.tool_name}({json.dumps(event.args, indent=2)})")
                return
            if isinstance(event, ToolResultEvent):
                if event.result.get("success"):
                    print(f"✅ Result: {str(event.result.get('result', 'Success'))[:200]}")
                else:
                    print(f"❌ Error: {event.result.get('error')}")
                self.hooks.fire_tool_result(event.tool_name, event.tool_call_id, event.result)
                self._autosave()
                return

        max_iterations = 10
        try:
            run_loop(
                messages=self.history.messages,
                tools=self.tools.get_tool_schemas(),
                execute_tool=lambda name, args: self.tools.execute_tool(name, args),
                config=LoopConfig(
                    model=resolve_model_alias(self.config.model),
                    system_prompt=self.history.system_prompt,
                    max_iterations=max_iterations,
                    temperature=self.config.temperature,
                    max_tokens=self.config.max_tokens,
                    stream=self.config.stream,
                    use_tools=self.config.use_tools,
                ),
                emitter=EventEmitter(on_event),
            )
        except Exception as e:
            error_str = str(e).lower()
            if "rate" in error_str and "limit" in error_str:
                print("❌ Rate limit hit. Waiting...")
                import time

                time.sleep(5)
                return self._send_to_llm_with_tools_internal()
            print(f"\n❌ Error calling LLM: {e}")
            import traceback

            traceback.print_exc()

    def _handle_streaming_with_tools(self, api_kwargs: Dict) -> Any:
        api_kwargs["stream"] = True
        stream = llm.completion(**api_kwargs)

        accumulated_content = ""
        accumulated_tool_calls: Dict[int, Dict[str, Any]] = {}

        print("\n🤖 Assistant:", end=" ")

        for chunk in stream:
            if self.interrupted:
                break

            delta = chunk.choices[0].delta

            if hasattr(delta, "content") and delta.content:
                content = delta.content
                print(content, end="", flush=True)
                accumulated_content += content

            if hasattr(delta, "tool_calls") and delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index

                    if idx not in accumulated_tool_calls:
                        accumulated_tool_calls[idx] = {
                            "id": "",
                            "type": "function",
                            "function": {"name": "", "arguments": ""},
                        }

                    if tc.id:
                        accumulated_tool_calls[idx]["id"] = tc.id
                    if hasattr(tc, "function") and tc.function:
                        if tc.function.name:
                            accumulated_tool_calls[idx]["function"][
                                "name"
                            ] = tc.function.name
                        if tc.function.arguments:
                            accumulated_tool_calls[idx]["function"][
                                "arguments"
                            ] += tc.function.arguments

        print()

        class Response:
            def __init__(self, content: str, tool_calls: Dict[int, Dict[str, Any]]):
                self.content = content
                self.tool_calls: List[Any] = []

                for tc_data in tool_calls.values():

                    class ToolCall:
                        def __init__(self, data: Dict[str, Any]):
                            self.id = data["id"]
                            self.type = data["type"]

                            class Function:
                                def __init__(self, func_data: Dict[str, Any]):
                                    self.name = func_data["name"]
                                    self.arguments = func_data["arguments"]

                            self.function = Function(data["function"])

                    self.tool_calls.append(ToolCall(tc_data))

        return Response(accumulated_content, accumulated_tool_calls)

    def _autosave(self) -> None:
        if hasattr(self, "session_manager") and self.session_manager:
            self.session_manager.save_current(self.history)
