import json
import subprocess
from pathlib import Path
from typing import List, Optional, Dict, Any, Set

from anvil import llm
from anvil.config import AgentConfig, resolve_model_alias
from anvil.history import MessageHistory
from anvil.git import GitRepo
from anvil.files import FileManager
from anvil.shell import ShellRunner
from anvil.parser import ResponseParser
from anvil.tools import ToolRegistry
from anvil.linter import Linter
from anvil.prompts import Prompts


class CodingAgentWithTools:
    def __init__(self, root_path: str, config: AgentConfig | None = None):
        self.root_path = Path(root_path)
        self.config = config or AgentConfig()

        self.history = MessageHistory()
        self.git = GitRepo(str(root_path))
        self.files = FileManager(str(root_path))
        self.shell = ShellRunner(
            str(root_path), auto_approve=self.config.approval_mode == "full-auto"
        )
        self.parser = ResponseParser()
        self.tools = ToolRegistry()
        self.linter = Linter(str(root_path))

        self.files_in_context: List[str] = []
        self.read_only_files: Set[str] = set()
        self.interrupted = False
        self.last_commit_hash: str | None = None
        self.last_edited_files: List[str] = []

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
        if self._is_read_only(filepath):
            return f"Refusing to write {filepath}: file is read-only"
        if not self._require_approval(f"write {filepath}"):
            return f"Write to {filepath} not approved"
        self.files.write_file(filepath, content)
        self.last_edited_files.append(filepath)
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
        if self._is_read_only(filepath):
            return f"Refusing to edit {filepath}: file is read-only"
        if not self._require_approval(f"edit {filepath}"):
            return f"Edit to {filepath} not approved"
        success = self.files.apply_edit(filepath, search, replace)
        if success:
            self.last_edited_files.append(filepath)
            return f"Edit applied successfully to {filepath}"
        else:
            return f"Failed to apply edit to {filepath} - search block not found"

    def _is_read_only(self, filepath: str) -> bool:
        return filepath in self.read_only_files

    def _require_approval(self, action: str) -> bool:
        if self.config.approval_mode != "suggest":
            return True
        response = input(f"Approve {action}? [y/N] ").strip().lower()
        if response in {"y", "yes"}:
            return True
        print(f"⚠️  Skipped: {action}")
        return False

    def _set_system_prompt(self):
        prompts = Prompts()
        if self.config.use_tools:
            system_prompt = prompts.main_system.format(root_path=self.root_path)
            self.history.set_system_prompt(system_prompt)
            self.history.add_example_messages(prompts.example_messages)
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

    def _set_system_prompt_base(self):
        prompts = Prompts()
        if self.config.use_tools:
            system_prompt = prompts.main_system.format(root_path=self.root_path)
            self.history.set_system_prompt(system_prompt)
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
        print(f"🤖 Anvil started (model: {self.config.model})")
        print("Commands: /help for all commands")
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
        cmd = parts[0].lstrip("/")
        args = parts[1] if len(parts) > 1 else ""

        handler = getattr(self, f"cmd_{cmd}", None)
        if handler:
            return handler(args)

        print(f"Unknown command: /{cmd}. Type /help for available commands.")
        return True

    def cmd_quit(self, args: str) -> bool:
        print("👋 Goodbye!")
        return False

    def cmd_exit(self, args: str) -> bool:
        return self.cmd_quit(args)

    def cmd_add(self, args: str) -> bool:
        if args:
            self.add_file_to_context(args)
        else:
            print("Usage: /add <filepath>")
        return True

    def cmd_drop(self, args: str) -> bool:
        if not args:
            print("Usage: /drop <filepath>")
            return True
        if args in self.files_in_context:
            self.files_in_context.remove(args)
            self.read_only_files.discard(args)
            print(f"✅ Dropped {args} from context")
        else:
            print(f"❌ {args} not in context")
        return True

    def cmd_read_only(self, args: str) -> bool:
        if not args:
            print("Usage: /read-only <filepath>")
            return True
        self.add_file_to_context(args)
        self.read_only_files.add(args)
        print(f"🔒 Marked {args} as read-only")
        return True

    def cmd_read_write(self, args: str) -> bool:
        if not args:
            print("Usage: /read-write <filepath>")
            return True
        if args in self.read_only_files:
            self.read_only_files.remove(args)
            print(f"✅ {args} is now writable")
        else:
            print(f"ℹ️  {args} was not read-only")
        return True

    def cmd_files(self, args: str) -> bool:
        if not self.files_in_context:
            print("No files in context")
        else:
            print("Files in context:")
            for f in self.files_in_context:
                suffix = " (read-only)" if f in self.read_only_files else ""
                print(f"  • {f}{suffix}")
        return True

    def cmd_clear(self, args: str) -> bool:
        self.history.clear()
        self.files_in_context.clear()
        self.read_only_files.clear()
        self._set_system_prompt()
        print("✅ Cleared chat history and context")
        return True

    def cmd_undo(self, args: str) -> bool:
        if not self.last_commit_hash:
            print("❌ No recent commit to undo")
            return True
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
        return True

    def cmd_model(self, args: str) -> bool:
        if not args:
            print(f"Current model: {self.config.model}")
            return True
        self.config.model = resolve_model_alias(args)
        print(f"✅ Switched to model: {self.config.model}")
        return True

    def cmd_approval(self, args: str) -> bool:
        if not args:
            print(f"Current approval mode: {self.config.approval_mode}")
            return True
        mode = args.strip().lower()
        if mode not in {"suggest", "auto-edit", "full-auto"}:
            print("Usage: /approval [suggest|auto-edit|full-auto]")
            return True
        self.config.approval_mode = mode
        self.shell.auto_approve = mode == "full-auto"
        print(f"✅ Approval mode set to: {mode}")
        return True

    def cmd_tokens(self, args: str) -> bool:
        try:
            import tiktoken

            enc = tiktoken.encoding_for_model("gpt-4o")
            messages = self.history.get_messages_for_api()
            total = sum(len(enc.encode(str(m.get("content", "")))) for m in messages)
            print(f"📊 Estimated tokens: ~{total:,}")
        except ImportError:
            msg_count = len(self.history.messages)
            print(
                f"📊 Messages in history: {msg_count} (install tiktoken for token count)"
            )
        return True

    def cmd_git(self, args: str) -> bool:
        if args == "status":
            print(self.git.get_status() or "Nothing to commit")
        elif args == "diff":
            print(self.git.get_diff() or "No changes")
        else:
            print("Usage: /git status or /git diff")
        return True

    def cmd_save(self, args: str) -> bool:
        if not args:
            print("Usage: /save <filepath>")
            return True
        path = self.root_path / args
        data = {
            "history": self.history.to_dict(),
            "files_in_context": self.files_in_context,
            "read_only_files": sorted(self.read_only_files),
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=2))
            print(f"✅ Session saved to {path}")
        except Exception as e:
            print(f"❌ Failed to save session: {e}")
        return True

    def cmd_load(self, args: str) -> bool:
        if not args:
            print("Usage: /load <filepath>")
            return True
        path = self.root_path / args
        try:
            data = json.loads(path.read_text())
        except Exception as e:
            print(f"❌ Failed to load session: {e}")
            return True
        history_data = data.get("history", {})
        self.history = MessageHistory.from_dict(history_data)
        if not self.history.system_prompt:
            self._set_system_prompt_base()
        self.files_in_context = data.get("files_in_context", [])
        self.read_only_files = set(data.get("read_only_files", []))
        print(f"✅ Session loaded from {path}")
        return True

    def cmd_test(self, args: str) -> bool:
        command = args.strip() or self.config.test_command
        print(f"🧪 Running tests: {command}")
        result = self.shell.run_command(command)
        if result["success"]:
            print(result["stdout"])
            return True
        output = "\n".join(
            [part for part in [result.get("stdout", ""), result.get("stderr", "")] if part]
        )
        print(output)
        self.history.add_user_message(
            f"Test run failed (command: {command}).\n\n{output}"
        )
        self._send_to_llm_with_tools()
        return True

    def cmd_help(self, args: str) -> bool:
        print(
            """
Commands:
  /add <file>     Add file to context
  /drop <file>    Remove file from context
  /read-only <file>  Add file to context as read-only
  /read-write <file> Remove read-only status
  /files          List files in context
  /clear          Clear chat history
  /undo           Revert last auto-commit
  /model [name]   Show or switch model
  /approval [mode] Set approval mode (suggest, auto-edit, full-auto)
  /tokens         Show token usage
  /git status     Show git status
  /git diff       Show git diff
  /save <file>    Save session to file
  /load <file>    Load session from file
  /test [cmd]     Run tests and feed failures to the agent
  /help           Show this help
  /quit           Exit
"""
        )
        return True

    def process_user_message(self, message: str):
        self.history.add_user_message(message)
        self._send_to_llm_with_tools()

    def _maybe_summarize_history(self):
        max_messages = self.config.summary_max_messages
        if max_messages <= 0:
            return
        if len(self.history.messages) <= max_messages:
            return
        keep_last = max(0, self.config.summary_keep_last)
        to_summarize = (
            self.history.messages[:-keep_last]
            if keep_last
            else list(self.history.messages)
        )
        if not to_summarize:
            return
        summary_model = self.config.summary_model or self.config.model
        prompt = (
            "Summarize the conversation so far for future context. "
            "Include key decisions, file changes, commands run, and open tasks. "
            "Be concise and factual."
        )
        if self.history.summary:
            prompt += f"\n\nExisting summary:\n{self.history.summary}"
        prompt += "\n\nMessages:\n" + json.dumps(to_summarize, indent=2)
        try:
            completion = llm.completion(
                model=summary_model,
                messages=[{"role": "user", "content": prompt}],
                stream=False,
                temperature=0.0,
                max_tokens=512,
            )
            summary = completion.choices[0].message.content
            if summary:
                self.history.set_summary(summary.strip())
                self.history.messages = self.history.messages[-keep_last:]
        except Exception as e:
            print(f"⚠️  Failed to summarize history: {e}")

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
        self._maybe_summarize_history()
        self._send_to_llm_with_tools_internal()
        self._lint_and_fix()

    def _send_to_llm_with_tools_internal(self):
        prompts = Prompts()
        messages = self.history.get_messages_for_api(system_reminder=prompts.system_reminder)

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

                    messages = self.history.get_messages_for_api(system_reminder=prompts.system_reminder)
                    continue

                if response.content:
                    self.history.add_assistant_message(content=response.content)
                    self._apply_edits(response.content)

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

        if self.config.approval_mode == "suggest" and not self._require_approval(
            f"apply {len(edits)} edit(s)"
        ):
            return

        edited_files = []

        for filename, search, replace in edits:
            print(f"  Editing {filename}...")

            if self._is_read_only(filename):
                print(f"  🔒 Skipped {filename} (read-only)")
                continue

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

        if (
            edited_files
            and self.config.auto_commit
            and self.config.approval_mode == "full-auto"
            and not self.config.dry_run
        ):
            try:
                commit_msg = "anvil: applied edits"
                hash_str, _ = self.git.commit(commit_msg, edited_files)
                self.last_commit_hash = hash_str
                print("✅ Auto-committed changes")
            except Exception as e:
                print(f"⚠️  Failed to commit: {e}")
