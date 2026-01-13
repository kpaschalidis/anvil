import os
import json
from pathlib import Path
from typing import List, Optional, Dict, Any
import openai

from anvil.config import AgentConfig
from anvil.history import MessageHistory
from anvil.git import GitRepo
from anvil.files import FileManager
from anvil.shell import ShellRunner
from anvil.parser import ResponseParser
from anvil.tools import ToolRegistry


class CodingAgentWithTools:
    def __init__(self, root_path: str, config: AgentConfig | None = None):
        self.root_path = Path(root_path)
        self.config = config or AgentConfig()

        self.history = MessageHistory()
        self.git = GitRepo(str(root_path))
        self.files = FileManager(str(root_path))
        self.shell = ShellRunner(str(root_path))
        self.parser = ResponseParser()
        self.tools = ToolRegistry()

        self.files_in_context: List[str] = []
        self.interrupted = False

        self.client = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

        self._register_tools()
        self._set_system_prompt()

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

    def _tool_read_file(self, filepath: str) -> str:
        return self.files.read_file(filepath)

    def _tool_write_file(self, filepath: str, content: str) -> str:
        self.files.write_file(filepath, content)
        return f"File {filepath} written successfully"

    def _tool_list_files(self, pattern: str = "*") -> str:
        files = self.files.list_files(pattern)
        return "\n".join(files) if files else "No files found"

    def _tool_run_command(self, command: str) -> str:
        result = self.shell.run_command(command)

        if result["success"]:
            return f"Exit code: {result['exit_code']}\n\nOutput:\n{result['stdout']}"
        else:
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
            return f"Edit applied successfully to {filepath}"
        else:
            return f"Failed to apply edit to {filepath} - search block not found"

    def _set_system_prompt(self):
        if self.config.use_tools:
            prompt = """You are an expert coding assistant with access to tools.

You can:
1. Read files with read_file(filepath)
2. Write files with write_file(filepath, content)
3. List files with list_files(pattern)
4. Apply edits with apply_edit(filepath, search, replace)
5. Run commands with run_command(command)
6. Check git status with git_status()
7. View git diff with git_diff()

When making edits:
- Use apply_edit() for targeted changes
- Use write_file() for new files or complete rewrites
- Always read_file() first to see current contents

Be concise and helpful."""
        else:
            prompt = """You are an expert coding assistant. You can edit files using search/replace blocks:

filename.py
```python
<<<<<<< SEARCH
old code
=======
new code
>>>>>>> REPLACE
```

Be concise and helpful."""

        self.history.set_system_prompt(prompt)

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

    def run(self, initial_message: Optional[str] = None):
        print("🤖 Coding Agent started (with tools)")
        print("Commands: /quit, /add <file>, /git status, /git diff")
        print()

        if initial_message:
            self.process_user_message(initial_message)

        while True:
            try:
                user_input = input("\n> ").strip()

                if not user_input:
                    continue

                if user_input.startswith("/"):
                    if self._handle_command(user_input):
                        continue
                    else:
                        break

                self.process_user_message(user_input)

            except KeyboardInterrupt:
                print("\n\n⚠️  Interrupted")
                self.interrupted = True
                break
            except EOFError:
                break
            except Exception as e:
                print(f"\n❌ Error: {e}")
                import traceback
                traceback.print_exc()

    def _handle_command(self, command: str) -> bool:
        parts = command.split(maxsplit=1)
        cmd = parts[0]
        args = parts[1] if len(parts) > 1 else ""

        if cmd == "/quit" or cmd == "/exit":
            print("👋 Goodbye!")
            return False

        elif cmd == "/add":
            if args:
                self.add_file_to_context(args)
            else:
                print("Usage: /add <filepath>")

        elif cmd == "/git":
            if args == "status":
                print(self.git.get_status())
            elif args == "diff":
                print(self.git.get_diff())
            else:
                print("Usage: /git status or /git diff")

        elif cmd == "/help":
            print(
                """
Commands:
  /add <file>   - Add file to context
  /git status   - Show git status
  /git diff     - Show git diff
  /quit         - Exit
            """
            )

        else:
            print(f"Unknown command: {cmd}")

        return True

    def process_user_message(self, message: str):
        self.history.add_user_message(message)
        self._send_to_llm_with_tools()

    def _send_to_llm_with_tools(self):
        messages = self.history.get_messages_for_api()

        max_iterations = 10
        iteration = 0

        while iteration < max_iterations:
            iteration += 1

            try:
                api_kwargs: Dict[str, Any] = {
                    "model": self.config.model,
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
                    completion = self.client.chat.completions.create(**api_kwargs)
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

                    messages = self.history.get_messages_for_api()
                    continue

                if response.content:
                    self.history.add_assistant_message(content=response.content)
                    self._apply_edits(response.content)

                break

            except openai.RateLimitError:
                print("❌ Rate limit hit. Waiting...")
                import time
                time.sleep(5)
                continue

            except Exception as e:
                print(f"\n❌ Error calling LLM: {e}")
                import traceback
                traceback.print_exc()
                break

    def _handle_streaming_with_tools(self, api_kwargs: Dict) -> Any:
        stream = self.client.chat.completions.create(**api_kwargs, stream=True)

        accumulated_content = ""
        accumulated_tool_calls: Dict[int, Dict[str, Any]] = {}

        print("\n🤖 Assistant:", end=" ")

        for chunk in stream:
            if self.interrupted:
                break

            delta = chunk.choices[0].delta

            if delta.content:
                content = delta.content
                print(content, end="", flush=True)
                accumulated_content += content

            if delta.tool_calls:
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
                    if tc.function.name:
                        accumulated_tool_calls[idx]["function"]["name"] = tc.function.name
                    if tc.function.arguments:
                        accumulated_tool_calls[idx]["function"]["arguments"] += tc.function.arguments

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
            else:
                print(f"  ❌ Failed to edit {filename}")

        if edited_files and self.config.auto_commit and not self.config.dry_run:
            try:
                commit_msg = "aider: applied edits"
                self.git.commit(commit_msg, edited_files)
                print("✅ Auto-committed changes")
            except Exception as e:
                print(f"⚠️  Failed to commit: {e}")
