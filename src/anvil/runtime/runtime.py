import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List

from common import llm
from anvil.config import AgentConfig, resolve_model_alias
from anvil.files import FileManager
from anvil.git import GitRepo
from anvil.history import MessageHistory
from anvil.linter import Linter
from anvil.parser import ResponseParser
from anvil.shell import ShellRunner
from anvil.tools import ToolRegistry
from anvil.prompts import build_main_system_prompt, load_prompt_blocks
from anvil.ext.markdown_executor import MarkdownExecutor
from anvil.ext.markdown_loader import MarkdownIndex
from anvil.sessions.manager import SessionManager
from anvil.subagents.registry import AgentRegistry
from anvil.subagents.task_tool import SubagentRunner, TaskTool


class AnvilRuntime:
    def __init__(self, root_path: str, config: AgentConfig | None = None):
        self.root_path = Path(root_path)
        self.config = config or AgentConfig()

        self.history = MessageHistory()
        self.git = GitRepo(str(root_path))
        self.files = FileManager(str(root_path))
        self.shell = ShellRunner(str(root_path))
        self.parser = ResponseParser()
        self.tools = ToolRegistry()
        self.linter = Linter(str(root_path))

        self.files_in_context: List[str] = []
        self.interrupted = False
        self.last_commit_hash: str | None = None
        self.last_edited_files: List[str] = []

        self.markdown_index = MarkdownIndex(self.root_path)
        self.markdown_index.reload()
        self.markdown_executor = MarkdownExecutor(
            self.root_path, self.history, self._send_to_llm_with_tools
        )

        self.agent_registry = AgentRegistry(self.root_path)
        self.agent_registry.reload()

        self.vendored_prompts = load_prompt_blocks()
        self._register_tools()
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
            name="git_diff",
            description="Get the current git diff",
            parameters={"type": "object", "properties": {}, "required": []},
            implementation=self._tool_git_diff,
        )

        self.tools.register_tool(
            name="git_status",
            description="Get the current git status",
            parameters={"type": "object", "properties": {}, "required": []},
            implementation=self._tool_git_status,
        )

        self.tools.register_tool(
            name="apply_edit",
            description="Apply a search and replace edit to a file",
            parameters={
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "Path to the file"},
                    "search": {
                        "type": "string",
                        "description": "Text to search for (must match exactly or fuzzy match)",
                    },
                    "replace": {
                        "type": "string",
                        "description": "Text to replace with",
                    },
                },
                "required": ["filepath", "search", "replace"],
            },
            implementation=self._tool_apply_edit,
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
        self.last_edited_files.append(filepath)
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

    def _tool_git_diff(self) -> str:
        diff = self.git.get_diff()
        return diff if diff else "No changes"

    def _tool_git_status(self) -> str:
        status = self.git.get_status()
        return status if status else "Nothing to commit"

    def _tool_apply_edit(self, filepath: str, search: str, replace: str) -> str:
        success = self.files.apply_edit(filepath, search, replace)
        if success:
            self.last_edited_files.append(filepath)
            return f"Edit applied successfully to {filepath}"
        return f"Failed to apply edit to {filepath} - search block not found"

    def _tool_skill(self, name: str) -> str:
        entry = self.markdown_index.skills.get(name)
        if not entry:
            return f"Skill not found: {name}"
        return entry.body

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

    def _lint_and_fix(self, max_retries: int | None = None):
        if not self.config.auto_lint or not self.last_edited_files:
            return

        retries = max_retries or self.config.lint_fix_retries
        files_to_lint = list(set(self.last_edited_files))
        self.last_edited_files.clear()

        for attempt in range(retries):
            errors = []
            for filepath in files_to_lint:
                result = self.linter.lint(filepath)
                if result:
                    errors.append(f"## {filepath}\n{result.text}")

            if not errors:
                return

            print(f"🔍 Lint errors found (attempt {attempt + 1}/{retries})")
            error_msg = "Fix these lint errors:\n\n" + "\n\n".join(errors)
            self.history.add_user_message(error_msg)
            self._send_to_llm_with_tools_internal()
            files_to_lint = list(set(self.last_edited_files))
            self.last_edited_files.clear()

        if errors:
            print("⚠️  Could not auto-fix all lint errors")

    def _send_to_llm_with_tools(self):
        self._send_to_llm_with_tools_internal()
        self._lint_and_fix()

    def _send_to_llm_with_tools_internal(self):
        messages = self.history.get_messages_for_api()

        max_iterations = 10
        iteration = 0

        while iteration < max_iterations:
            iteration += 1

            try:
                api_kwargs: Dict[str, Any] = {
                    "model": resolve_model_alias(self.config.model),
                    "messages": messages,
                    "temperature": self.config.temperature,
                    "max_tokens": self.config.max_tokens,
                }

                if self.config.use_tools:
                    api_kwargs["tools"] = self.tools.get_tool_schemas()
                    api_kwargs["tool_choice"] = "auto"

                if self.config.stream:
                    response = self._handle_streaming_with_tools(api_kwargs)
                else:
                    completion = llm.completion(**api_kwargs)
                    response = completion.choices[0].message

                if hasattr(response, "tool_calls") and response.tool_calls:
                    tool_calls = response.tool_calls

                    self.history.add_assistant_message(
                        content=response.content,
                        tool_calls=[
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments,
                                },
                            }
                            for tc in tool_calls
                        ],
                    )

                    for tool_call in tool_calls:
                        tool_name = tool_call.function.name
                        tool_args = json.loads(tool_call.function.arguments)

                        print(
                            f"\n🔧 Calling: {tool_name}({json.dumps(tool_args, indent=2)})"
                        )

                        result = self.tools.execute_tool(tool_name, tool_args)
                        result_str = json.dumps(result)

                        if result.get("success"):
                            print(f"✅ Result: {result.get('result', 'Success')[:200]}")
                        else:
                            print(f"❌ Error: {result.get('error')}")

                        self.history.add_tool_result(
                            tool_call_id=tool_call.id, name=tool_name, result=result_str
                        )
                        self._autosave()

                    messages = self.history.get_messages_for_api()
                    continue

                if response.content:
                    self.history.add_assistant_message(content=response.content)
                    self._apply_edits(response.content)
                    self._autosave()

                break

            except Exception as e:
                error_str = str(e).lower()
                if "rate" in error_str and "limit" in error_str:
                    print("❌ Rate limit hit. Waiting...")
                    import time

                    time.sleep(5)
                    continue

                print(f"\n❌ Error calling LLM: {e}")
                import traceback

                traceback.print_exc()
                break

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

    def _apply_edits(self, response: str):
        edits = self.parser.parse_edits(response)

        if not edits:
            return

        print(f"\n📝 Applying {len(edits)} edit(s)...")

        edited_files = []

        for filename, search, replace in edits:
            print(f"  Editing {filename}...")

            if self.config.dry_run:
                print(f"    [DRY RUN] Would edit {filename}")
                continue

            success = self.files.apply_edit(filename, search, replace)

            if success:
                print(f"  ✅ {filename} updated")
                edited_files.append(filename)
                self.last_edited_files.append(filename)
            else:
                print(f"  ❌ Failed to edit {filename}")

        if edited_files and self.config.auto_commit and not self.config.dry_run:
            try:
                commit_msg = "anvil: applied edits"
                hash_str, _ = self.git.commit(commit_msg, edited_files)
                self.last_commit_hash = hash_str
                print("✅ Auto-committed changes")
            except Exception as e:
                print(f"⚠️  Failed to commit: {e}")

    def undo_last_commit(self) -> None:
        if not self.last_commit_hash:
            print("❌ No recent commit to undo")
            return
        try:
            subprocess.run(
                ["git", "reset", "--soft", "HEAD~1"],
                cwd=self.root_path,
                check=True,
                capture_output=True,
            )
            print(f"✅ Reverted commit {self.last_commit_hash[:8]}")
            self.last_commit_hash = None
        except subprocess.CalledProcessError as e:
            print(f"❌ Failed to undo: {e}")

    def _autosave(self) -> None:
        if hasattr(self, "session_manager") and self.session_manager:
            self.session_manager.save_current(self.history)
