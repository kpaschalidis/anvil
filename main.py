#!/usr/bin/env python3
"""
PRODUCTION AGENT LOOP WITH STRUCTURED TOOLS
Based on Aider + OpenAI Function Calling

This version includes REAL tool support using OpenAI's function calling API.
"""

import os
import sys
import re
import subprocess
import json
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any, Callable
from dataclasses import dataclass
from enum import Enum
import openai

# ============================================================================
# CONFIGURATION
# ============================================================================


@dataclass
class AgentConfig:
    """Configuration for the agent"""

    model: str = "gpt-4o"
    temperature: float = 0.0
    max_tokens: int = 4096
    auto_commit: bool = True
    dry_run: bool = False
    max_retries: int = 3
    stream: bool = True
    use_tools: bool = True  # Enable function calling


# ============================================================================
# TOOL DEFINITIONS
# ============================================================================


class ToolRegistry:
    """Registry of available tools for the agent"""

    def __init__(self):
        self.tools: Dict[str, Dict[str, Any]] = {}
        self.implementations: Dict[str, Callable] = {}

    def register_tool(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        implementation: Callable,
    ):
        """Register a tool with its schema and implementation"""

        # OpenAI function calling schema
        self.tools[name] = {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters,
            },
        }

        self.implementations[name] = implementation

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        """Get all tool schemas for OpenAI API"""
        return list(self.tools.values())

    def execute_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a tool by name"""
        if name not in self.implementations:
            return {"error": f"Tool {name} not found"}

        try:
            result = self.implementations[name](**arguments)
            return {"success": True, "result": result}
        except Exception as e:
            return {"success": False, "error": str(e)}


# ============================================================================
# MESSAGE HISTORY WITH TOOL SUPPORT
# ============================================================================


class MessageHistory:
    """Manages conversation history including tool calls"""

    def __init__(self):
        self.messages: List[Dict[str, Any]] = []
        self.system_prompt: Optional[str] = None

    def set_system_prompt(self, prompt: str):
        """Set the system prompt"""
        self.system_prompt = prompt

    def add_user_message(self, content: str):
        """Add user message to history"""
        self.messages.append({"role": "user", "content": content})

    def add_assistant_message(
        self, content: Optional[str] = None, tool_calls: Optional[List[Dict]] = None
    ):
        """Add assistant message (may include tool calls)"""
        message = {"role": "assistant"}

        if content:
            message["content"] = content

        if tool_calls:
            message["tool_calls"] = tool_calls

        self.messages.append(message)

    def add_tool_result(self, tool_call_id: str, name: str, result: str):
        """Add tool execution result"""
        self.messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "name": name,
                "content": result,
            }
        )

    def get_messages_for_api(self) -> List[Dict[str, Any]]:
        """Get messages formatted for OpenAI API"""
        if self.system_prompt:
            return [{"role": "system", "content": self.system_prompt}] + self.messages
        return self.messages

    def clear(self):
        """Clear all messages (keeps system prompt)"""
        self.messages = []


# ============================================================================
# GIT INTEGRATION
# ============================================================================


class GitRepo:
    """Git repository integration"""

    def __init__(self, root_path: str):
        self.root_path = Path(root_path)
        self._ensure_git_repo()

    def _ensure_git_repo(self):
        """Check if we're in a git repository"""
        try:
            subprocess.run(
                ["git", "rev-parse", "--git-dir"],
                cwd=self.root_path,
                capture_output=True,
                check=True,
            )
        except subprocess.CalledProcessError:
            raise Exception("Not a git repository")

    def commit(self, message: str, files: List[str]) -> Tuple[str, str]:
        """Commit changes"""
        try:
            for file in files:
                subprocess.run(["git", "add", file], cwd=self.root_path, check=True)

            subprocess.run(
                ["git", "commit", "-m", message],
                cwd=self.root_path,
                capture_output=True,
                text=True,
                check=True,
            )

            hash_result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=self.root_path,
                capture_output=True,
                text=True,
                check=True,
            )

            return (hash_result.stdout.strip(), message)

        except subprocess.CalledProcessError as e:
            raise Exception(f"Git commit failed: {e.stderr}")

    def get_diff(self) -> str:
        """Get current diff"""
        result = subprocess.run(
            ["git", "diff"], cwd=self.root_path, capture_output=True, text=True
        )
        return result.stdout

    def get_status(self) -> str:
        """Get git status"""
        result = subprocess.run(
            ["git", "status", "--short"],
            cwd=self.root_path,
            capture_output=True,
            text=True,
        )
        return result.stdout


# ============================================================================
# FILE OPERATIONS
# ============================================================================


class FileManager:
    """Manages file operations"""

    def __init__(self, root_path: str):
        self.root_path = Path(root_path)

    def read_file(self, filepath: str) -> str:
        """Read file contents"""
        full_path = self.root_path / filepath
        try:
            return full_path.read_text()
        except Exception as e:
            raise Exception(f"Error reading {filepath}: {str(e)}")

    def write_file(self, filepath: str, content: str):
        """Write content to file"""
        full_path = self.root_path / filepath
        try:
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content)
        except Exception as e:
            raise Exception(f"Error writing {filepath}: {str(e)}")

    def list_files(self, pattern: str = "*") -> List[str]:
        """List files matching pattern"""
        files = []
        for path in self.root_path.rglob(pattern):
            if path.is_file():
                files.append(str(path.relative_to(self.root_path)))
        return files

    def apply_edit(self, filepath: str, search: str, replace: str) -> bool:
        """Apply search/replace edit"""
        try:
            content = self.read_file(filepath)

            if search in content:
                new_content = content.replace(search, replace, 1)
                self.write_file(filepath, new_content)
                return True

            new_content = self._fuzzy_replace(content, search, replace)
            if new_content:
                self.write_file(filepath, new_content)
                return True

            return False

        except Exception as e:
            print(f"Error applying edit: {e}")
            return False

    def _fuzzy_replace(self, content: str, search: str, replace: str) -> Optional[str]:
        """Fuzzy string replacement"""

        def normalize(text):
            return " ".join(text.split())

        search_norm = normalize(search)
        content_norm = normalize(content)

        search_start = content_norm.find(search_norm)
        if search_start == -1:
            return None

        # Map back to original (simplified version)
        orig_pos = 0
        norm_pos = 0

        for i, char in enumerate(content):
            if (
                content_norm[norm_pos : norm_pos + len(search_norm)] == search_norm
                and norm_pos == search_start
            ):
                start_pos = i
                break
            if not char.isspace():
                norm_pos += 1
        else:
            return None

        search_end = search_start + len(search_norm)
        norm_pos = search_start
        for i in range(start_pos, len(content)):
            if norm_pos >= search_end:
                end_pos = i
                break
            if not content[i].isspace():
                norm_pos += 1
        else:
            end_pos = len(content)

        return content[:start_pos] + replace + content[end_pos:]


# ============================================================================
# SHELL COMMAND EXECUTION
# ============================================================================


class ShellRunner:
    """Execute shell commands"""

    def __init__(self, root_path: str, auto_approve: bool = False):
        self.root_path = Path(root_path)
        self.auto_approve = auto_approve

    def run_command(self, command: str) -> Dict[str, Any]:
        """Run a shell command"""
        if not self.auto_approve:
            print(f"\n🔧 Command to run: {command}")
            response = input("Execute? (y/n): ")
            if response.lower() != "y":
                return {
                    "success": False,
                    "error": "User cancelled",
                    "stdout": "",
                    "stderr": "",
                    "exit_code": -1,
                }

        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=self.root_path,
                capture_output=True,
                text=True,
                timeout=30,
            )

            return {
                "success": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "exit_code": result.returncode,
            }

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": "Command timed out",
                "stdout": "",
                "stderr": "",
                "exit_code": -1,
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "stdout": "",
                "stderr": "",
                "exit_code": -1,
            }


# ============================================================================
# RESPONSE PARSER (for non-tool edits)
# ============================================================================


class ResponseParser:
    """Parse LLM responses for edits"""

    @staticmethod
    def parse_edits(response: str) -> List[Tuple[str, str, str]]:
        """Parse search/replace blocks"""
        edits = []

        pattern = r"""
            (?P<filename>[\w\-./]+\.\w+)\s*
            ```(?:\w+)?\s*
            <<<<<<< \s* SEARCH\s*
            (?P<search>.*?)
            =======\s*
            (?P<replace>.*?)
            >>>>>>> \s* REPLACE\s*
            ```
        """

        for match in re.finditer(pattern, response, re.DOTALL | re.VERBOSE):
            filename = match.group("filename")
            search = match.group("search").strip()
            replace = match.group("replace").strip()
            edits.append((filename, search, replace))

        return edits


# ============================================================================
# THE MAIN AGENT WITH TOOLS
# ============================================================================


class CodingAgentWithTools:
    """
    Production coding agent with structured tool support
    """

    def __init__(self, root_path: str, config: AgentConfig = None):
        self.root_path = Path(root_path)
        self.config = config or AgentConfig()

        # Components
        self.history = MessageHistory()
        self.git = GitRepo(str(root_path))
        self.files = FileManager(str(root_path))
        self.shell = ShellRunner(str(root_path))
        self.parser = ResponseParser()
        self.tools = ToolRegistry()

        # State
        self.files_in_context: List[str] = []
        self.interrupted = False

        # OpenAI client
        self.client = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

        # Register tools
        self._register_tools()

        # Set system prompt
        self._set_system_prompt()

    def _register_tools(self):
        """Register all available tools"""

        # Tool 1: Read File
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

        # Tool 2: Write File
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

        # Tool 3: List Files
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

        # Tool 4: Run Shell Command
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

        # Tool 5: Git Diff
        self.tools.register_tool(
            name="git_diff",
            description="Get the current git diff",
            parameters={"type": "object", "properties": {}, "required": []},
            implementation=self._tool_git_diff,
        )

        # Tool 6: Git Status
        self.tools.register_tool(
            name="git_status",
            description="Get the current git status",
            parameters={"type": "object", "properties": {}, "required": []},
            implementation=self._tool_git_status,
        )

        # Tool 7: Apply Edit
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

    # Tool implementations
    def _tool_read_file(self, filepath: str) -> str:
        """Read file implementation"""
        return self.files.read_file(filepath)

    def _tool_write_file(self, filepath: str, content: str) -> str:
        """Write file implementation"""
        self.files.write_file(filepath, content)
        return f"File {filepath} written successfully"

    def _tool_list_files(self, pattern: str = "*") -> str:
        """List files implementation"""
        files = self.files.list_files(pattern)
        return "\n".join(files) if files else "No files found"

    def _tool_run_command(self, command: str) -> str:
        """Run command implementation"""
        result = self.shell.run_command(command)

        if result["success"]:
            return f"Exit code: {result['exit_code']}\n\nOutput:\n{result['stdout']}"
        else:
            error = result.get("error", result.get("stderr", "Unknown error"))
            return f"Command failed: {error}"

    def _tool_git_diff(self) -> str:
        """Git diff implementation"""
        diff = self.git.get_diff()
        return diff if diff else "No changes"

    def _tool_git_status(self) -> str:
        """Git status implementation"""
        status = self.git.get_status()
        return status if status else "Nothing to commit"

    def _tool_apply_edit(self, filepath: str, search: str, replace: str) -> str:
        """Apply edit implementation"""
        success = self.files.apply_edit(filepath, search, replace)
        if success:
            return f"Edit applied successfully to {filepath}"
        else:
            return f"Failed to apply edit to {filepath} - search block not found"

    def _set_system_prompt(self):
        """Set the agent's system prompt"""
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
        """Add a file to the conversation context"""
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
        """Main run loop"""
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
        """Handle slash commands"""
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
        """
        Process message through the loop with tool support
        """
        self.history.add_user_message(message)

        # Send to LLM with tools
        self._send_to_llm_with_tools()

    def _send_to_llm_with_tools(self):
        """
        Send to LLM with tool support - handles tool calls in loop
        """
        messages = self.history.get_messages_for_api()

        max_iterations = 10  # Prevent infinite loops
        iteration = 0

        while iteration < max_iterations:
            iteration += 1

            try:
                # Prepare API call
                api_kwargs = {
                    "model": self.config.model,
                    "messages": messages,
                    "temperature": self.config.temperature,
                    "max_tokens": self.config.max_tokens,
                }

                # Add tools if enabled
                if self.config.use_tools:
                    api_kwargs["tools"] = self.tools.get_tool_schemas()
                    api_kwargs["tool_choice"] = "auto"

                # Make API call
                if self.config.stream:
                    response = self._handle_streaming_with_tools(api_kwargs)
                else:
                    completion = self.client.chat.completions.create(**api_kwargs)
                    response = completion.choices[0].message

                # Check if we got tool calls
                if hasattr(response, "tool_calls") and response.tool_calls:
                    # Execute tools
                    tool_calls = response.tool_calls

                    # Add assistant message with tool calls
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

                    # Execute each tool
                    for tool_call in tool_calls:
                        tool_name = tool_call.function.name
                        tool_args = json.loads(tool_call.function.arguments)

                        print(
                            f"\n🔧 Calling: {tool_name}({json.dumps(tool_args, indent=2)})"
                        )

                        # Execute tool
                        result = self.tools.execute_tool(tool_name, tool_args)
                        result_str = json.dumps(result)

                        # Show result
                        if result.get("success"):
                            print(f"✅ Result: {result.get('result', 'Success')[:200]}")
                        else:
                            print(f"❌ Error: {result.get('error')}")

                        # Add tool result to history
                        self.history.add_tool_result(
                            tool_call_id=tool_call.id, name=tool_name, result=result_str
                        )

                    # Update messages and continue loop
                    messages = self.history.get_messages_for_api()
                    continue

                # No tool calls - we're done
                if response.content:
                    self.history.add_assistant_message(content=response.content)

                    # Also parse for manual edits (fallback)
                    self._apply_edits(response.content)

                break  # Exit loop

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
        """
        Handle streaming response with tool calls
        Note: OpenAI streaming with tools is complex - accumulate chunks
        """
        stream = self.client.chat.completions.create(**api_kwargs, stream=True)

        accumulated_content = ""
        accumulated_tool_calls = {}

        print("\n🤖 Assistant:", end=" ")

        for chunk in stream:
            if self.interrupted:
                break

            delta = chunk.choices[0].delta

            # Accumulate content
            if delta.content:
                content = delta.content
                print(content, end="", flush=True)
                accumulated_content += content

            # Accumulate tool calls
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
                        accumulated_tool_calls[idx]["function"][
                            "name"
                        ] = tc.function.name
                    if tc.function.arguments:
                        accumulated_tool_calls[idx]["function"][
                            "arguments"
                        ] += tc.function.arguments

        print()  # Newline

        # Create response object
        class Response:
            def __init__(self, content, tool_calls):
                self.content = content
                self.tool_calls = []

                # Convert accumulated tool calls to proper format
                for tc_data in tool_calls.values():

                    class ToolCall:
                        def __init__(self, data):
                            self.id = data["id"]
                            self.type = data["type"]

                            class Function:
                                def __init__(self, func_data):
                                    self.name = func_data["name"]
                                    self.arguments = func_data["arguments"]

                            self.function = Function(data["function"])

                    self.tool_calls.append(ToolCall(tc_data))

        return Response(accumulated_content, accumulated_tool_calls)

    def _apply_edits(self, response: str):
        """Parse and apply edits from text (fallback)"""
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

        # Auto-commit
        if edited_files and self.config.auto_commit and not self.config.dry_run:
            try:
                commit_msg = "aider: applied edits"
                self.git.commit(commit_msg, edited_files)
                print(f"✅ Auto-committed changes")
            except Exception as e:
                print(f"⚠️  Failed to commit: {e}")


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description="Coding Agent with Tools")
    parser.add_argument("--model", default="gpt-4o", help="Model to use")
    parser.add_argument("--no-stream", action="store_true", help="Disable streaming")
    parser.add_argument(
        "--dry-run", action="store_true", help="Don't actually edit files"
    )
    parser.add_argument(
        "--no-auto-commit", action="store_true", help="Don't auto-commit"
    )
    parser.add_argument(
        "--no-tools", action="store_true", help="Disable structured tools"
    )
    parser.add_argument("files", nargs="*", help="Files to add to context")
    parser.add_argument("--message", "-m", help="Initial message")

    args = parser.parse_args()

    if not os.environ.get("OPENAI_API_KEY"):
        print("❌ Error: OPENAI_API_KEY environment variable not set")
        sys.exit(1)

    config = AgentConfig(
        model=args.model,
        stream=not args.no_stream,
        dry_run=args.dry_run,
        auto_commit=not args.no_auto_commit,
        use_tools=not args.no_tools,
    )

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
        root_path = result.stdout.strip()
    except subprocess.CalledProcessError:
        print("❌ Error: Not in a git repository")
        sys.exit(1)

    agent = CodingAgentWithTools(root_path, config)

    for filepath in args.files:
        agent.add_file_to_context(filepath)

    agent.run(initial_message=args.message)


if __name__ == "__main__":
    main()
