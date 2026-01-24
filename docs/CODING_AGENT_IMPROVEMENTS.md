# Improving Anvil's Coding Agent to Claude Code Level

This document describes how to enhance Anvil's coding capabilities to match Claude Code's production-grade features.

## Executive Summary

**Current State:** Anvil is at **75-80% Claude Code parity** with an excellent foundation.

**Core strengths (already match Claude Code):**
- ✅ Agent loop architecture (ReACT pattern, single-threaded)
- ✅ Tool execution system
- ✅ Basic tool set (file ops, search, execution)
- ✅ CLI approval for dangerous commands
- ✅ Session save/load

**Critical gaps (2 weeks to fix):**
- ❌ Context compression (causes failures on long sessions)
- ❌ Project memory (no continuity across sessions)
- ❌ JSONL transcripts (can't resume from arbitrary points)
- ❌ Hook system (limited extensibility)
- ❌ File operation approval (accidental overwrites possible)

**Timeline to Claude Code parity:**
- **2 weeks:** 90% parity (MVP - production-ready)
- **3 weeks:** 95% parity (all core features)
- **4 weeks:** 100% parity (feature-complete)

**Bottom line:** Your agent loop and tool system are production-grade. You're missing infrastructure features (compression, hooks, transcripts) more than core capabilities.

## Current State Assessment

### What Anvil Already Has (Production-Grade)

| Component | Status | Quality |
|-----------|--------|---------|
| **Core agent loop** | ✅ Complete | 8/10 - Matches Claude Code pattern |
| **Tool system** | ✅ Complete | 7/10 - Fewer tools than Claude Code |
| **Tool approval (CLI)** | ✅ Complete | 7/10 - Blocking approval works |
| **Streaming** | ✅ Complete | 8/10 - Built-in |
| **Sub-agents** | ✅ Complete | 8/10 - Parallel workers pattern |
| **Session management** | ✅ Complete | 7/10 - Save/load works |

### What's Missing for Claude Code Parity

| Feature | Current | Claude Code | Priority | Impact |
|---------|---------|-------------|----------|--------|
| **Context compression** | ❌ None | ✅ Auto at 92% | Critical | High |
| **Project memory** | ❌ None | ✅ CLAUDE.md | Critical | High |
| **Planning tools** | ❌ None | ✅ TodoWrite/Read | High | Medium |
| **Hook system** | ❌ None | ✅ 10 events | High | High |
| **Tool approval granularity** | ⚠️ Shell only | ✅ Per-tool + hooks | High | High |
| **MultiEdit** | ❌ None | ✅ Built-in | Medium | Medium |
| **Persistent shell** | ❌ Each subprocess | ✅ Persistent session | Medium | Low |
| **Stop control** | ❌ Max iterations only | ✅ Hook-based | Medium | Medium |
| **Permission modes** | ❌ On/off only | ✅ 5 modes | Medium | Medium |
| **Diff preview** | ❌ None | ✅ Colorized | Low | Medium |
| **Notebook support** | ❌ None | ✅ Read/Edit | Low | Low |
| **Real-time steering** | ❌ None | ✅ h2A queue | Low | Low |

## Feature-by-Feature Comparison

### Complete Feature Matrix

| Feature | Anvil | Claude Code | Status | Effort |
|---------|-------|-------------|--------|--------|
| **Core Loop** |
| ReACT pattern | ✅ | ✅ | ✅ Match | 0 |
| Single-threaded | ✅ | ✅ | ✅ Match | 0 |
| Max iterations | ✅ (10) | ✅ (~25) | ⚠️ Increase | 0.1 day |
| Streaming | ✅ | ✅ | ✅ Match | 0 |
| Tool call streaming | ❌ | ✅ | ❌ Missing | 1 day |
| Context compression | ❌ | ✅ (auto 92%) | ❌ Missing | 3 days |
| Stop hooks | ❌ | ✅ | ❌ Missing | 1 day |
| **Tools** |
| read_file | ✅ | ✅ (Read) | ✅ Match | 0 |
| write_file | ✅ | ✅ (Write) | ✅ Match | 0 |
| str_replace | ✅ | ✅ (Edit) | ✅ Match | 0 |
| grep | ✅ | ✅ (Grep) | ✅ Match | 0 |
| glob | ✅ | ✅ (Glob) | ✅ Match | 0 |
| list_files | ✅ | ✅ (LS) | ✅ Match | 0 |
| run_command | ✅ (isolated) | ✅ (Bash, persistent) | ⚠️ Not persistent | 2 days |
| TodoWrite | ❌ | ✅ | ❌ Missing | 1 day |
| TodoRead | ❌ | ✅ | ❌ Missing | 0.5 day |
| MultiEdit | ❌ | ✅ | ❌ Missing | 1 day |
| BashOutput | ❌ | ✅ | ❌ Missing | 0.5 day |
| KillShell | ❌ | ✅ | ❌ Missing | 0.5 day |
| NotebookRead | ❌ | ✅ | ❌ Missing | 1 day |
| NotebookEdit | ❌ | ✅ | ❌ Missing | 1 day |
| SlashCommand | ❌ | ✅ | ❌ Missing | 0.5 day |
| **Approval & Safety** |
| Shell approval | ✅ (CLI) | ✅ | ✅ Match | 0 |
| File write approval | ❌ | ✅ | ❌ Missing | 0.5 day |
| Permission modes | ❌ | ✅ (5 modes) | ❌ Missing | 1 day |
| Hook system | ❌ | ✅ (10 events) | ❌ Missing | 4 days |
| Diff preview | ❌ | ✅ | ❌ Missing | 0.5 day |
| **Sub-agents** |
| Spawn subagents | ✅ | ✅ | ✅ Match | 0 |
| Agent types | ❌ | ✅ (4 types) | ❌ Missing | 2 days |
| Context isolation | ❌ | ✅ | ❌ Missing | 1 day |
| Max concurrent | 5 | 1 (coding) | ⚠️ Too high | 0.5 day |
| Subagent hooks | ❌ | ✅ | ❌ Missing | Included in hooks |
| **Memory & Context** |
| Session save/load | ✅ (JSON) | ✅ (JSONL) | ⚠️ Format | 1 day |
| Project memory | ❌ | ✅ (CLAUDE.md) | ❌ Missing | 2 days |
| Auto-summarization | ❌ | ✅ | ❌ Missing | Included in compression |
| Context pruning | ❌ | ✅ | ❌ Missing | Included in compression |
| Resume checkpoints | ⚠️ Session-level | ✅ Per-action | ⚠️ Coarse | 1 day |

### Score Calculation

**Current scores explained:**

- **Agent loop (8/10):** Core is perfect, missing compression (-1), missing stop hooks (-1)
- **Tool system (7/10):** File ops perfect, missing 16 tools (-2), core 6 critical (-1)
- **Tool approval (7/10):** Shell works, no file approval (-2), no hooks (-1)
- **Streaming (8/10):** Content perfect, no tool streaming (-1), no cancel (-1)
- **Sub-agents (8/10):** Spawning works, no types (-1), no isolation (-1)
- **Sessions (7/10):** Basic works, no JSONL (-1), no fine checkpoints (-1), no analytics (-1)

**Each component can reach 10/10 by implementing the missing features listed above.**

## Architecture Comparison

### Claude Code Architecture

```
┌─────────────────────────────────────────────────────────┐
│                  Claude Code Stack                       │
│                                                          │
│  User Layer (CLI/VSCode/Web)                            │
│         ↓                                                │
│  Master Loop (nO) + Async Queue (h2A)                   │
│         ↓                                                │
│  ┌──────────────────────────────────────┐              │
│  │ StreamGen (streaming output)         │              │
│  │ ToolEngine (orchestrates tools)      │              │
│  │ Compressor (auto at 92% context)     │              │
│  └──────────────────────────────────────┘              │
│         ↓                                                │
│  Tools (24 total):                                       │
│  - File ops (Read, Edit, Write, MultiEdit, Glob)       │
│  - Search (Grep, LS)                                    │
│  - Execute (Bash, BashOutput, KillShell)                │
│  - Planning (TodoWrite, TodoRead)                       │
│  - Web (WebFetch, WebSearch)                            │
│  - Sub-agents (Task/Agent, max 1 concurrent)            │
│  - Notebooks (NotebookRead, NotebookEdit)               │
│         ↓                                                │
│  Hook System (10 events):                               │
│  - PreToolUse, PostToolUse, PermissionRequest           │
│  - Stop, SubagentStop, UserPromptSubmit                 │
│  - SessionStart, SessionEnd, PreCompact                 │
│         ↓                                                │
│  Memory:                                                 │
│  - CLAUDE.md (project memory)                           │
│  - Auto-compress at 92% context                         │
│  - Persistent shell env vars                            │
└─────────────────────────────────────────────────────────┘
```

### Anvil's Current Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Anvil Stack                           │
│                                                          │
│  CLI (REPL)                                             │
│         ↓                                                │
│  agent_loop.py (210 LOC)                                │
│         ↓                                                │
│  SubagentRunner + ParallelWorkerRunner                  │
│         ↓                                                │
│  Tools (8 total):                                        │
│  - File ops (read_file, str_replace, write_file)        │
│  - Search (grep, glob, list_files)                      │
│  - Execute (run_command - with approval)                │
│  - Web (web_search, web_extract)                        │
│         ↓                                                │
│  Approval:                                               │
│  - ShellRunner (CLI blocking)                           │
│         ↓                                                │
│  Memory:                                                 │
│  - SessionManager (JSON files)                          │
│  - Manual save/load                                     │
└─────────────────────────────────────────────────────────┘
```

## Gap Analysis: What to Add

### 1. Planning Tools (TodoWrite/TodoRead)

**What Claude Code Has:**

```
Agent: [Calls TodoWrite]
{
  "todos": [
    {"id": "auth-1", "content": "Create JWT module", "status": "pending"},
    {"id": "auth-2", "content": "Add middleware", "status": "pending"},
    {"id": "auth-3", "content": "Update routes", "status": "pending"}
  ]
}

[UI renders interactive checklist]

Agent: [Works on auth-1]
Agent: [Calls TodoWrite to update]
{
  "todos": [
    {"id": "auth-1", "status": "completed"},
    ...
  ]
}
```

**How Anvil Can Implement:**

File: `src/anvil/tools/todo.py` (~100 LOC)

```python
class TodoManager:
    """Manage task lists for coding sessions."""
    
    def __init__(self, session_dir: Path):
        self.todos_file = session_dir / "todos.json"
        self.todos: list[dict] = self._load()
    
    def write_todos(self, todos: list[dict]) -> dict:
        """Write/update entire todo list."""
        # Validate todos have id, content, status
        for todo in todos:
            if not todo.get("id") or not todo.get("content"):
                return {"error": "Todos must have id and content"}
        
        self.todos = todos
        self._save()
        return {"success": True, "todos": todos}
    
    def read_todos(self) -> dict:
        """Read current todo list."""
        return {"todos": self.todos}
    
    def _save(self):
        self.todos_file.write_text(json.dumps(self.todos, indent=2))
    
    def _load(self):
        if self.todos_file.exists():
            return json.loads(self.todos_file.read_text())
        return []

# Register as tool
tool_registry.register_tool(
    "todo_write",
    "Write or update the task list",
    parameters={...},
    implementation=todo_manager.write_todos
)
```

**Effort:** 1 day  
**Impact:** Medium - Improves planning visibility

### 2. Context Compression (Auto at 92%)

**What Claude Code Has:**

- Monitors context window usage
- At 92% full, automatically triggers `Compressor wU2`
- Summarizes conversation
- Moves summary to `CLAUDE.md` (project memory)
- Clears old messages, keeps recent

**How Anvil Can Implement:**

File: `src/anvil/memory/compressor.py` (~150 LOC)

```python
class ContextCompressor:
    """Auto-compress context when approaching limits."""
    
    def __init__(self, model: str, max_tokens: int = 128000):
        self.model = model
        self.max_tokens = max_tokens
        self.threshold = 0.92  # Compress at 92%
    
    def should_compress(self, messages: list[dict]) -> bool:
        """Check if compression needed."""
        token_count = estimate_tokens(messages)
        return token_count > self.max_tokens * self.threshold
    
    def compress(
        self,
        messages: list[dict],
        memory_file: Path
    ) -> list[dict]:
        """Compress messages and update memory file."""
        # 1. Summarize conversation
        summary = self._summarize_conversation(messages)
        
        # 2. Append to CLAUDE.md
        self._append_to_memory(memory_file, summary)
        
        # 3. Keep only recent messages (last 20%)
        keep_count = int(len(messages) * 0.2)
        recent = messages[-keep_count:]
        
        # 4. Add memory file reference
        memory_msg = {
            "role": "system",
            "content": f"Project context in {memory_file.name}. Key facts: {summary[:500]}"
        }
        
        return [memory_msg] + recent
    
    def _summarize_conversation(self, messages: list[dict]) -> str:
        """Summarize messages using LLM."""
        prompt = f"""Summarize this conversation, focusing on:
        - Key decisions made
        - Files created/modified
        - Important context to remember
        
        Messages:
        {json.dumps(messages[-50:], indent=2)[:8000]}
        
        Return concise summary (max 500 words)."""
        
        resp = llm.completion(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1000
        )
        return resp.choices[0].message.content
    
    def _append_to_memory(self, memory_file: Path, summary: str):
        """Append summary to CLAUDE.md."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        entry = f"\n## Session {timestamp}\n\n{summary}\n"
        
        if memory_file.exists():
            content = memory_file.read_text()
            memory_file.write_text(content + entry)
        else:
            memory_file.write_text(f"# Project Memory\n{entry}")
```

**Integration into agent_loop.py:**

```python
def run_loop(messages, tools, execute_tool, config, emitter):
    compressor = ContextCompressor(config.model)
    memory_file = Path(".claude/MEMORY.md")
    
    for iteration in range(config.max_iterations):
        # Check if compression needed
        if compressor.should_compress(messages):
            messages = compressor.compress(messages, memory_file)
            if emitter:
                emitter.emit(ContextCompressedEvent())
        
        # Continue with normal loop
        response = llm.completion(messages, tools)
        # ...
```

**Token Estimation:**

```python
def estimate_tokens(messages: list[dict]) -> int:
    """Rough token estimation (4 chars ≈ 1 token)."""
    total_chars = sum(
        len(json.dumps(msg)) for msg in messages
    )
    return total_chars // 4
```

**Effort:** 2-3 days  
**Impact:** High - Prevents context overflow, enables longer sessions

**This alone takes agent loop from 8/10 → 9/10**

### 3. Hook System

**What Claude Code Has:**

A complete event-driven hook system with 10 events:

```
PreToolUse → Can modify tool args, approve/deny/ask
PostToolUse → Can validate results, provide feedback
PermissionRequest → Intercept permission dialogs
UserPromptSubmit → Validate/enhance user input
Stop → Control when agent stops
SubagentStop → Control when sub-agent stops
PreCompact → Before context compression
SessionStart → Load context at startup
SessionEnd → Cleanup on exit
Notification → Handle system notifications
```

**How Anvil Can Implement:**

File: `src/anvil/hooks/manager.py` (~300 LOC)

```python
from enum import Enum
from typing import Callable, Any

class HookEvent(Enum):
    PRE_TOOL_USE = "pre_tool_use"
    POST_TOOL_USE = "post_tool_use"
    PERMISSION_REQUEST = "permission_request"
    USER_PROMPT_SUBMIT = "user_prompt_submit"
    STOP = "stop"
    SESSION_START = "session_start"
    SESSION_END = "session_end"

class HookManager:
    """Event-driven hook system for coding agent."""
    
    def __init__(self):
        self.hooks: dict[HookEvent, list[Callable]] = {
            event: [] for event in HookEvent
        }
    
    def register(self, event: HookEvent, handler: Callable):
        """Register a hook handler."""
        self.hooks[event].append(handler)
    
    def trigger(self, event: HookEvent, data: dict[str, Any]) -> dict[str, Any]:
        """Trigger all hooks for an event."""
        results = []
        for handler in self.hooks[event]:
            try:
                result = handler(data)
                results.append(result)
            except Exception as e:
                print(f"Hook failed: {e}")
        
        # Merge results (first deny wins, etc.)
        return self._merge_results(results)
    
    def _merge_results(self, results: list[dict]) -> dict:
        """Merge multiple hook results."""
        # If any hook denies, deny
        if any(r.get("decision") == "deny" for r in results):
            denied = next(r for r in results if r.get("decision") == "deny")
            return denied
        
        # Merge additional context
        context = []
        for r in results:
            if r.get("additional_context"):
                context.append(r["additional_context"])
        
        return {
            "decision": "allow",
            "additional_context": "\n".join(context) if context else None
        }

# Example hook: Auto-approve documentation file reads
def auto_approve_docs_hook(data: dict) -> dict:
    """Auto-approve reading documentation files."""
    if data["tool_name"] != "read_file":
        return {"decision": "allow"}
    
    file_path = data["tool_args"].get("path", "")
    if file_path.endswith((".md", ".txt", ".json")):
        return {
            "decision": "allow",
            "reason": "Documentation file auto-approved"
        }
    
    return {"decision": "ask"}  # Ask for other files

# Register
hook_manager.register(HookEvent.PRE_TOOL_USE, auto_approve_docs_hook)
```

**Integration into agent_loop.py:**

```python
def run_loop(messages, tools, execute_tool, config, emitter, hook_manager=None):
    for iteration in range(config.max_iterations):
        response = llm.completion(messages, tools)
        
        if response.tool_calls:
            for tool_call in response.tool_calls:
                # Trigger PreToolUse hooks
                if hook_manager:
                    hook_result = hook_manager.trigger(
                        HookEvent.PRE_TOOL_USE,
                        {
                            "tool_name": tool_call.function.name,
                            "tool_args": json.loads(tool_call.function.arguments)
                        }
                    )
                    
                    if hook_result.get("decision") == "deny":
                        # Add denial message to context
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_call.function.name,
                            "content": json.dumps({
                                "error": hook_result.get("reason", "Denied by hook")
                            })
                        })
                        continue
                
                # Execute tool
                result = execute_tool(tool_name, tool_args)
                
                # Trigger PostToolUse hooks
                if hook_manager:
                    hook_manager.trigger(HookEvent.POST_TOOL_USE, {...})
```

**Effort:** 3-4 days  
**Impact:** High - Enables fine-grained control, auto-approvals, validation

### 4. Enhanced Editing Tools

**What Claude Code Has:**

- `Edit` - String replacement (like your `str_replace`)
- `MultiEdit` - Edit multiple files at once
- Diff-based display (shows colorized diffs)

**What Anvil Has:**

- `str_replace` - String replacement (equivalent to `Edit`)
- `write_file` - Full file write

**What's Missing:**

- `MultiEdit` - Batch editing
- Diff preview before approval

**How Anvil Can Implement:**

File: `src/anvil/tools/multi_edit.py` (~80 LOC)

```python
def multi_edit(edits: list[dict]) -> dict:
    """Edit multiple files in one operation.
    
    Args:
        edits: [
            {"path": "file1.py", "old_string": "...", "new_string": "..."},
            {"path": "file2.py", "old_string": "...", "new_string": "..."}
        ]
    """
    results = []
    
    for edit in edits:
        try:
            result = str_replace(
                path=edit["path"],
                old_string=edit["old_string"],
                new_string=edit["new_string"]
            )
            results.append({"path": edit["path"], "success": True})
        except Exception as e:
            results.append({"path": edit["path"], "success": False, "error": str(e)})
    
    return {
        "success": all(r["success"] for r in results),
        "results": results
    }
```

**Diff Preview:**

File: `src/anvil/tools/diff_preview.py` (~50 LOC)

```python
import difflib

def show_diff_preview(path: str, old_string: str, new_string: str) -> str:
    """Generate colorized diff preview."""
    old_lines = old_string.splitlines(keepends=True)
    new_lines = new_string.splitlines(keepends=True)
    
    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=f"{path} (before)",
        tofile=f"{path} (after)",
        lineterm=""
    )
    
    return "\n".join(diff)
```

**Effort:** 1 day  
**Impact:** Medium - Improves batch editing efficiency

### 5. Project Memory System

**What Claude Code Has:**

- `CLAUDE.md` file in project root
- Auto-generated and maintained
- Contains project context, decisions, key facts
- Referenced during context compression
- Persists across sessions

**How Anvil Can Implement:**

File: `src/anvil/memory/project_memory.py` (~120 LOC)

```python
class ProjectMemory:
    """Manage project-level memory file."""
    
    def __init__(self, project_root: Path):
        self.memory_file = project_root / ".anvil" / "MEMORY.md"
        self.memory_file.parent.mkdir(exist_ok=True)
    
    def append_session_summary(self, summary: str):
        """Append session summary to memory."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        entry = f"\n## Session {timestamp}\n\n{summary}\n"
        
        if self.memory_file.exists():
            content = self.memory_file.read_text()
            self.memory_file.write_text(content + entry)
        else:
            header = """# Project Memory

This file contains accumulated context about the project.
It's automatically updated by Anvil to help maintain continuity across sessions.

"""
            self.memory_file.write_text(header + entry)
    
    def get_recent_context(self, max_chars: int = 4000) -> str:
        """Get recent context for system prompt."""
        if not self.memory_file.exists():
            return ""
        
        content = self.memory_file.read_text()
        if len(content) <= max_chars:
            return content
        
        # Return most recent content
        return "...\n" + content[-max_chars:]
    
    def append_decision(self, decision: str):
        """Record an important decision."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        entry = f"- [{timestamp}] {decision}\n"
        
        # Find or create Decisions section
        if self.memory_file.exists():
            content = self.memory_file.read_text()
            if "## Key Decisions" in content:
                # Append to existing section
                parts = content.split("## Key Decisions")
                updated = parts[0] + "## Key Decisions\n" + entry + parts[1]
                self.memory_file.write_text(updated)
            else:
                # Create section
                self.memory_file.write_text(
                    content + f"\n## Key Decisions\n\n{entry}"
                )
```

**Integration:**

```python
# In agent loop or workflow
memory = ProjectMemory(project_root)

# At session start, load context
recent_context = memory.get_recent_context()
system_prompt = f"{base_system_prompt}\n\nProject context:\n{recent_context}"

# During session, record decisions
if important_decision:
    memory.append_decision("Chose JWT over OAuth for simplicity")

# At session end, save summary
summary = summarize_session(messages)
memory.append_session_summary(summary)
```

**Effort:** 2 days  
**Impact:** Medium - Better continuity across sessions

### 6. Persistent Shell Sessions

**What Claude Code Has:**

- Bash tool maintains persistent shell session
- Environment variables persist across commands
- Can run background processes
- Session state saved in transcript

**What Anvil Has:**

- Each `run_command` is isolated (new subprocess)
- No persistent environment

**How Anvil Can Implement:**

File: `src/anvil/tools/persistent_shell.py` (~200 LOC)

```python
import subprocess
import threading

class PersistentShell:
    """Persistent shell session for coding agent."""
    
    def __init__(self, cwd: str):
        self.cwd = cwd
        self.process = None
        self.env_vars = {}
        self._start_session()
    
    def _start_session(self):
        """Start persistent bash session."""
        self.process = subprocess.Popen(
            ["/bin/bash"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self.cwd,
            text=True,
            bufsize=1
        )
    
    def run_command(
        self,
        command: str,
        timeout: int = 30,
        background: bool = False
    ) -> dict:
        """Run command in persistent session."""
        if background:
            # Run in background, return immediately
            self.process.stdin.write(f"{command} &\n")
            self.process.stdin.flush()
            return {"success": True, "background": True}
        
        # Run synchronously
        self.process.stdin.write(f"{command}\n")
        self.process.stdin.write("echo '___ANVIL_CMD_END___'\n")
        self.process.stdin.flush()
        
        # Read until marker
        output_lines = []
        while True:
            line = self.process.stdout.readline()
            if "___ANVIL_CMD_END___" in line:
                break
            output_lines.append(line)
        
        return {
            "success": True,
            "stdout": "".join(output_lines),
            "stderr": ""
        }
    
    def set_env(self, key: str, value: str):
        """Set environment variable."""
        self.process.stdin.write(f"export {key}='{value}'\n")
        self.process.stdin.flush()
        self.env_vars[key] = value
    
    def close(self):
        """Terminate shell session."""
        if self.process:
            self.process.terminate()
```

**Effort:** 2 days  
**Impact:** Low - Nice to have, not critical

### 8. Permission Modes

**What Claude Code Has:**

Five permission modes:
- `default` - Ask for dangerous operations
- `plan` - Planning mode, no execution
- `acceptEdits` - Auto-approve file edits, ask for commands
- `dontAsk` - Auto-approve everything this session
- `bypassPermissions` - Complete bypass (dangerous)

**What Anvil Has:**

- `auto_approve: bool` - On/off only

**How Anvil Can Implement:**

File: `src/anvil/approval/permission_modes.py` (~100 LOC)

```python
from enum import Enum

class PermissionMode(Enum):
    DEFAULT = "default"           # Ask for dangerous ops
    PLAN = "plan"                 # Read-only, no execution
    ACCEPT_EDITS = "accept_edits" # Auto file edits, ask commands
    DONT_ASK = "dont_ask"         # Auto all this session
    BYPASS = "bypass"             # Complete bypass

class PermissionChecker:
    """Check if tool requires approval based on permission mode."""
    
    def __init__(self, mode: PermissionMode = PermissionMode.DEFAULT):
        self.mode = mode
    
    def requires_approval(self, tool_name: str, tool_args: dict) -> bool:
        """Check if tool requires user approval."""
        if self.mode == PermissionMode.BYPASS:
            return False
        
        if self.mode == PermissionMode.DONT_ASK:
            return False
        
        if self.mode == PermissionMode.PLAN:
            # Plan mode: block all execution
            if tool_name in ["write_file", "str_replace", "run_command"]:
                return True  # Will be denied, not asked
        
        if self.mode == PermissionMode.ACCEPT_EDITS:
            # Auto-approve file operations, ask for commands
            if tool_name in ["write_file", "str_replace"]:
                return False
            if tool_name == "run_command":
                return True
        
        if self.mode == PermissionMode.DEFAULT:
            # Ask for dangerous operations
            if tool_name == "run_command":
                return True
            if tool_name == "write_file" and self._is_sensitive_file(tool_args.get("path")):
                return True
        
        return False
    
    def _is_sensitive_file(self, path: str) -> bool:
        """Check if file is sensitive."""
        sensitive = [".env", ".git/", "id_rsa", "credentials", "secrets"]
        return any(s in path for s in sensitive)
```

**Integration:**

```python
# CLI with permission mode
anvil code --permission-mode accept_edits "Add auth"

# In agent_loop
permission_checker = PermissionChecker(mode=config.permission_mode)

for tool_call in response.tool_calls:
    if permission_checker.requires_approval(tool_name, tool_args):
        approval = input(f"Execute {tool_name}? (y/n): ")
        if approval != "y":
            continue
    
    result = execute_tool(tool_name, tool_args)
```

**Effort:** 1 day  
**Impact:** Medium - Better control, safer execution

### 9. Enhanced Tool Approval for File Operations

**What Claude Code Does:**

- File writes require approval by default
- Can be configured via hooks or permission modes
- Shows diff preview before approval

**What Anvil Does:**

- File writes auto-approved (no checkpoint)
- Only shell commands require approval

**How to Fix:**

```python
# In execute_tool()
def execute_tool(tool_name: str, args: dict) -> dict:
    # Check if approval needed
    if permission_checker.requires_approval(tool_name, args):
        # Show preview for file operations
        if tool_name in ["write_file", "str_replace"]:
            show_diff_preview(args)
        
        approval = input(f"Execute {tool_name}? (y/n): ")
        if approval != "y":
            return {"error": "User denied"}
    
    # Execute
    return tool_registry.execute_tool(tool_name, args)
```

**Effort:** 0.5 day  
**Impact:** High - Prevents accidental overwrites

### 10. Agent Types and Context Isolation

**What Claude Code Has:**

Sub-agent types:
- `Explore` - Codebase exploration
- `Plan` - Planning and strategy
- `Code` - Code implementation
- `Test` - Testing and validation
- Custom agents via `--agent` or `--agents` flag

Each sub-agent has:
- Isolated message history
- Separate transcript file
- Max 1 concurrent for coding

**What Anvil Has:**

- Generic `SubagentRunner`
- Up to 5 parallel workers (for research)
- Shared message history

**How Anvil Can Implement:**

File: `src/anvil/agents/agent_types.py` (~150 LOC)

```python
from dataclasses import dataclass
from enum import Enum

class AgentType(Enum):
    EXPLORE = "explore"
    PLAN = "plan"
    CODE = "code"
    TEST = "test"
    RESEARCH = "research"

@dataclass
class AgentDefinition:
    """Definition of a specialized agent."""
    type: AgentType
    system_prompt: str
    allowed_tools: list[str]
    max_iterations: int
    isolated_context: bool

BUILTIN_AGENTS = {
    "explore": AgentDefinition(
        type=AgentType.EXPLORE,
        system_prompt="""You are an exploration agent.
        Your goal is to understand the codebase structure.
        Use read_file, grep, glob, and list_files to explore.
        Do NOT make any changes.""",
        allowed_tools=["read_file", "grep", "glob", "list_files"],
        max_iterations=10,
        isolated_context=True
    ),
    
    "plan": AgentDefinition(
        type=AgentType.PLAN,
        system_prompt="""You are a planning agent.
        Break down the task into clear steps.
        Use TodoWrite to create a structured plan.
        Do NOT execute the plan.""",
        allowed_tools=["read_file", "list_files", "todo_write"],
        max_iterations=6,
        isolated_context=True
    ),
    
    "code": AgentDefinition(
        type=AgentType.CODE,
        system_prompt="""You are a coding agent.
        Implement changes according to the plan.
        Use file operations and test your changes.""",
        allowed_tools=["read_file", "write_file", "str_replace", "run_command"],
        max_iterations=20,
        isolated_context=False  # Needs main context
    ),
}

class IsolatedSubagent:
    """Sub-agent with isolated message context."""
    
    def __init__(self, agent_def: AgentDefinition, parent_session_id: str):
        self.agent_def = agent_def
        self.agent_id = generate_id()
        self.parent_id = parent_session_id
        self.messages = []  # Isolated from parent
        self.transcript_path = Path(
            f".anvil/sessions/{parent_session_id}/subagents/{self.agent_id}.jsonl"
        )
    
    def run(self, task_prompt: str) -> dict:
        """Run sub-agent with isolated context."""
        self.messages = [
            {"role": "system", "content": self.agent_def.system_prompt},
            {"role": "user", "content": task_prompt}
        ]
        
        result = run_loop(
            messages=self.messages,
            tools=self._get_allowed_tools(),
            execute_tool=self._execute_tool,
            config=LoopConfig(
                model=config.model,
                max_iterations=self.agent_def.max_iterations
            )
        )
        
        # Save transcript
        self._save_transcript()
        
        return {
            "agent_id": self.agent_id,
            "agent_type": self.agent_def.type.value,
            "result": result.final_response
        }
```

**Usage:**

```python
# Main agent wants to spawn sub-agent for exploration
if tool_call.name == "spawn_agent":
    agent_type = tool_args["agent_type"]  # "explore", "plan", etc.
    task = tool_args["task"]
    
    agent_def = BUILTIN_AGENTS[agent_type]
    subagent = IsolatedSubagent(agent_def, session_id)
    
    result = subagent.run(task)
    # Result fed back to main agent
```

**Effort:** 2 days  
**Impact:** Medium - Better separation of concerns

### 11. JSONL Transcript Format

**What Claude Code Has:**

Append-only JSONL transcript:
```jsonl
{"type":"user","content":"Add auth","timestamp":"2026-01-24T10:00:00Z"}
{"type":"assistant","content":"I'll add JWT auth","timestamp":"2026-01-24T10:00:01Z"}
{"type":"tool_use","tool":"read_file","args":{...},"timestamp":"2026-01-24T10:00:02Z"}
{"type":"tool_result","tool":"read_file","result":{...},"timestamp":"2026-01-24T10:00:03Z"}
```

**Benefits:**
- Append-only (safe for concurrent access)
- Checkpoint after every action
- Resume from any point
- Easy to parse/replay

**What Anvil Has:**

JSON file with full message array (overwrite on save)

**How Anvil Can Implement:**

File: `src/anvil/sessions/transcript.py` (~120 LOC)

```python
import json
from pathlib import Path
from datetime import datetime

class TranscriptWriter:
    """Append-only JSONL transcript."""
    
    def __init__(self, session_id: str, project_dir: Path):
        self.path = project_dir / ".anvil" / "sessions" / f"{session_id}.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
    
    def append_user_message(self, content: str):
        """Append user message to transcript."""
        self._append({
            "type": "user",
            "content": content,
            "timestamp": self._now()
        })
    
    def append_assistant_message(self, content: str, tool_calls: list = None):
        """Append assistant message."""
        entry = {
            "type": "assistant",
            "content": content,
            "timestamp": self._now()
        }
        if tool_calls:
            entry["tool_calls"] = tool_calls
        self._append(entry)
    
    def append_tool_use(self, tool_name: str, args: dict, tool_id: str):
        """Append tool use event."""
        self._append({
            "type": "tool_use",
            "tool": tool_name,
            "args": args,
            "tool_id": tool_id,
            "timestamp": self._now()
        })
    
    def append_tool_result(self, tool_id: str, result: dict):
        """Append tool result event."""
        self._append({
            "type": "tool_result",
            "tool_id": tool_id,
            "result": result,
            "timestamp": self._now()
        })
    
    def _append(self, entry: dict):
        """Append entry to JSONL file."""
        with open(self.path, "a") as f:
            f.write(json.dumps(entry) + "\n")
    
    def _now(self) -> str:
        return datetime.utcnow().isoformat() + "Z"
    
    def read_transcript(self) -> list[dict]:
        """Read full transcript."""
        if not self.path.exists():
            return []
        
        entries = []
        with open(self.path) as f:
            for line in f:
                entries.append(json.loads(line))
        return entries
    
    def resume_from_checkpoint(self, checkpoint_id: int) -> list[dict]:
        """Resume from specific line number."""
        entries = self.read_transcript()
        return entries[:checkpoint_id]
```

**Integration:**

```python
# In agent_loop.py
def run_loop(messages, tools, execute_tool, config, transcript=None):
    for iteration in range(config.max_iterations):
        response = llm.completion(messages, tools)
        
        # Append to transcript
        if transcript:
            transcript.append_assistant_message(
                response.content,
                tool_calls=response.tool_calls
            )
        
        if response.tool_calls:
            for tool_call in response.tool_calls:
                if transcript:
                    transcript.append_tool_use(
                        tool_call.function.name,
                        json.loads(tool_call.function.arguments),
                        tool_call.id
                    )
                
                result = execute_tool(tool_name, tool_args)
                
                if transcript:
                    transcript.append_tool_result(tool_call.id, result)
```

**Effort:** 1 day  
**Impact:** High - Enables fine-grained resume, better debugging

**This takes session management from 7/10 → 9/10**

### 7. Stop Control (Dynamic Continuation)

**What Claude Code Has:**

- `Stop` hook fires when agent wants to stop
- Can force agent to continue if work incomplete
- LLM-based or script-based decision

**How Anvil Can Implement:**

```python
# In agent_loop.py
def run_loop(messages, tools, execute_tool, config, emitter, hook_manager=None):
    for iteration in range(config.max_iterations):
        response = llm.completion(messages, tools)
        
        if not response.tool_calls:
            # Agent wants to stop
            if hook_manager:
                stop_result = hook_manager.trigger(
                    HookEvent.STOP,
                    {
                        "messages": messages,
                        "iteration": iteration,
                        "response": response.content
                    }
                )
                
                if stop_result.get("decision") == "continue":
                    # Force agent to continue
                    messages.append({
                        "role": "system",
                        "content": stop_result.get("reason", "Please continue")
                    })
                    continue
            
            # Normal stop
            return response.content
```

**Example Stop Hook:**

```python
def check_work_complete(data: dict) -> dict:
    """Check if work is actually complete."""
    messages = data["messages"]
    
    # Simple check: look for incomplete todos
    has_pending_todos = any(
        "TODO" in msg.get("content", "") or "[pending]" in msg.get("content", "")
        for msg in messages[-10:]
    )
    
    if has_pending_todos:
        return {
            "decision": "continue",
            "reason": "You have pending TODOs. Please complete them before stopping."
        }
    
    return {"decision": "allow"}
```

**Effort:** 1-2 days  
**Impact:** Medium - Prevents premature stopping

## Implementation Priority for Claude Code Parity

### Phase 1: Critical Infrastructure (Week 1-2)

**Must-have to prevent failures and enable long sessions:**

1. **Context compression** (2-3 days) - Auto at 92%, prevents overflow ⭐⭐⭐
2. **JSONL transcript** (1 day) - Fine-grained checkpoints, resume ⭐⭐⭐
3. **Project memory** (2 days) - MEMORY.md for continuity ⭐⭐⭐
4. **Permission modes** (1 day) - 5 modes like Claude Code ⭐⭐

**Total: 6-7 days**  
**Impact: Agent loop 8/10 → 9/10, Sessions 7/10 → 9/10**

### Phase 2: Core Features (Week 3)

**Essential tools and control:**

5. **Todo tools** (1 day) - TodoWrite/TodoRead ⭐⭐
6. **Hook system** (3-4 days) - 10 events, extensibility ⭐⭐⭐
7. **File operation approval** (0.5 day) - Approve write_file/str_replace ⭐⭐
8. **Stop control** (1 day) - Stop hooks, force continue ⭐⭐

**Total: 5-7 days**  
**Impact: Tool approval 7/10 → 9/10, Tool system 7/10 → 9/10**

### Phase 3: Polish and Advanced Features (Week 4)

**Nice-to-have for full parity:**

9. **Agent types** (2 days) - Explore, Plan, Code, Test agents ⭐
10. **MultiEdit tool** (1 day) - Batch editing ⭐
11. **Diff preview** (0.5 day) - Colorized diffs ⭐
12. **Persistent shell** (2 days) - Stateful bash session
13. **Enhanced streaming** (1 day) - Tool call streaming, cancellation

**Total: 6-7 days**  
**Impact: Sub-agents 8/10 → 10/10, Streaming 8/10 → 10/10**

## Total Implementation Timeline

**Phase 1 (Critical):** 6-7 days → 85% Claude Code parity  
**Phase 2 (Core):** 5-7 days → 95% Claude Code parity  
**Phase 3 (Polish):** 6-7 days → 100% Claude Code parity  

**Grand Total: 17-21 days (3-4 weeks) for exact Claude Code parity**

## What Gets You to Each Level

### 80% Parity (Current State)
- Core agent loop works ✅
- Basic tools available ✅
- Shell command approval ✅
- Session save/load ✅

### 90% Parity (After Phase 1 + 2)
- Context compression ✅
- Project memory ✅
- Hook system ✅
- Todo tools ✅
- JSONL transcript ✅
- File operation approval ✅
- Permission modes ✅

**Missing:** Agent types, MultiEdit, persistent shell

### 100% Parity (After Phase 3)
- All Phase 1 + 2 features ✅
- Agent types (Explore, Plan, Code, Test) ✅
- MultiEdit tool ✅
- Diff preview ✅
- Persistent shell ✅
- Enhanced streaming ✅

**Feature-complete with Claude Code.**

## File Structure After Implementation

```
src/anvil/
  memory/
    compressor.py        - Context compression
    project_memory.py    - MEMORY.md management
  
  hooks/
    manager.py           - Hook system core
    builtin_hooks.py     - Default hooks (auto-approve docs, etc.)
  
  tools/
    todo.py              - TodoWrite/TodoRead
    multi_edit.py        - MultiEdit tool
    diff_preview.py      - Diff generation
    persistent_shell.py  - Persistent bash session
  
  # Existing (keep as-is)
  agent_loop.py          - Core ReACT loop (unchanged)
  subagents/             - Sub-agent infrastructure (unchanged)
```

## Expected Outcome

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| **Context capacity** | ~100K tokens | Unlimited (auto-compress) | ∞ |
| **Session continuity** | Manual notes | Auto MEMORY.md | High |
| **Planning visibility** | Hidden | Todo lists | High |
| **Extensibility** | Limited | Hook system | High |
| **Tools** | 8 | 12+ | +50% |
| **Approval granularity** | Tool-level only | Tool + hook-based | High |

## Key Design Principles from Claude Code

### 1. Simplicity First

> "Do the simple thing first—choosing regex over embeddings for search, Markdown files over databases for memory."

**Applied to Anvil:**
- Memory file is simple Markdown, not database
- Todo is JSON file, not complex state management
- Hooks are Python functions, not complex event bus

### 2. Single-Threaded, Sequential

> "Coding is fundamentally dependency-driven."

**Applied to Anvil:**
- Keep single-threaded agent loop
- No parallel file editing
- Sequential tool execution

### 3. Bounded Context

> "Auto-compress at 92% to prevent context overflow."

**Applied to Anvil:**
- Monitor token usage
- Auto-compress when needed
- Keep recent messages, summarize old

### 4. Transparent and Auditable

> "Every tool call and message is logged, creating a complete audit trail."

**Applied to Anvil:**
- Keep existing trace system
- Add hook logging
- Persist all decisions

## What NOT to Copy from Claude Code

| Feature | Why Skip |
|---------|----------|
| **Multi-modal input** | Not essential for coding, adds complexity |
| **h2A async queue** | Over-engineered for your use case |
| **Plugin system** | Can use hooks for extensibility |
| **MCP protocol** | Complex, can add later if needed |
| **Notebook support** | Niche use case |
| **Web UI** | Separate concern, plan later |

## Summary: Anvil → Claude Code Level

### Component-by-Component Path to 10/10

| Component | Current | After Phase 1 | After Phase 2 | After Phase 3 | Missing for 10/10 |
|-----------|---------|---------------|---------------|---------------|-------------------|
| **Agent loop** | 8/10 | 9/10 | 9/10 | 10/10 | Stop hooks, compression |
| **Tool system** | 7/10 | 7/10 | 9/10 | 10/10 | Todos, MultiEdit, agent types |
| **Tool approval** | 7/10 | 8/10 | 9/10 | 10/10 | File approval, hooks, modes |
| **Streaming** | 8/10 | 8/10 | 8/10 | 10/10 | Tool call streaming, cancel |
| **Sub-agents** | 8/10 | 8/10 | 8/10 | 10/10 | Agent types, isolation, max 1 |
| **Sessions** | 7/10 | 9/10 | 9/10 | 10/10 | JSONL, checkpoints |

### Overall Feature Parity

**Current:** 75% of Claude Code features

**After Phase 1 (1-2 weeks):** 85% feature parity
- ✅ Context compression
- ✅ Project memory
- ✅ JSONL transcripts
- ✅ Permission modes
- ⚠️ Still missing: Hooks, todos, agent types

**After Phase 2 (3 weeks):** 95% feature parity
- ✅ All Phase 1 features
- ✅ Hook system
- ✅ Todo tools
- ✅ File operation approval
- ✅ Stop control
- ⚠️ Still missing: Agent types, advanced features

**After Phase 3 (4 weeks):** 100% feature parity
- ✅ All Phase 1 + 2 features
- ✅ Agent types (Explore, Plan, Code, Test)
- ✅ MultiEdit
- ✅ Diff preview
- ✅ Persistent shell
- ✅ Enhanced streaming
- ✅ **Full Claude Code parity**

### What Remains Different (Acceptable)

These are UI/deployment differences, not core capability gaps:

| Feature | Claude Code | Anvil | Note |
|---------|-------------|-------|------|
| **Terminal UI** | Rich TUI with colors | Basic CLI | Can add later |
| **MCP protocol** | Built-in | Can add via hooks | Not critical |
| **Plugin ecosystem** | Marketplace | None yet | Future |
| **Web/VS Code UI** | Official | Plan separately | Different scope |
| **Auto-linting** | Via hooks | Via hooks (same) | ✅ Equivalent |

### Total Implementation Effort

**Phase 1:** 6-7 days → 85% parity (critical features)  
**Phase 2:** 5-7 days → 95% parity (core features)  
**Phase 3:** 6-7 days → 100% parity (polish)  

**Grand Total: 17-21 days (3-4 weeks) for exact Claude Code feature parity**

### ROI Analysis

| Investment | Return |
|------------|--------|
| **Phase 1 (1-2 weeks)** | Production-ready coding agent, prevents context failures |
| **Phase 2 (1 week)** | Fine-grained control, extensibility, better UX |
| **Phase 3 (1 week)** | Complete feature parity, advanced workflows |

**Recommendation:** Implement Phase 1 immediately (critical), Phase 2 based on usage, Phase 3 as needed.

## Minimum Viable Claude Code Parity (MVP)

If you can only implement 5 things, implement these to get 90% of Claude Code's value:

### The Essential 5

1. **Context Compression** (3 days) ⭐⭐⭐
   - Auto-compress at 92% context
   - Prevents all context overflow issues
   - Enables unlimited session length
   - **Impact: Agent loop 8/10 → 9/10**

2. **JSONL Transcript** (1 day) ⭐⭐⭐
   - Checkpoint after every action
   - Resume from any point
   - Better debugging and audit trail
   - **Impact: Sessions 7/10 → 9/10**

3. **Hook System** (4 days) ⭐⭐⭐
   - 10 event types
   - PreToolUse, PostToolUse, Stop, etc.
   - Enables all advanced control
   - **Impact: Approval 7/10 → 9/10, Extensibility unlocked**

4. **TodoWrite/Read** (1 day) ⭐⭐
   - Agent can plan and track work
   - Better visibility for users
   - Matches Claude Code planning
   - **Impact: Tool system 7/10 → 8/10**

5. **File Operation Approval** (0.5 day) ⭐⭐
   - Approve write_file and str_replace
   - Prevents accidental overwrites
   - Matches Claude Code safety
   - **Impact: Approval 7/10 → 8/10**

**Total: 9.5 days (2 weeks)**  
**Result: 90% Claude Code parity on all critical dimensions**

### What This MVP Enables

After these 5 features:
- ✅ Unlimited session length (no context overflow)
- ✅ Safe file operations (approval for writes)
- ✅ Resume from any checkpoint (JSONL)
- ✅ Extensible via hooks (custom rules)
- ✅ Visible planning (todos)
- ✅ Production-ready for coding tasks

### What's Still Missing (Can Add Later)

- Agent types (Explore, Plan, Code)
- MultiEdit (batch operations)
- Permission modes (5 modes)
- Persistent shell
- Advanced streaming features

**These are valuable but not blocking for production use.**

## Final Recommendation

**To reach Claude Code level:**

**Option A: MVP (2 weeks)**
- Implement the Essential 5
- Get to 90% parity
- Production-ready for most coding tasks
- Can add remaining features incrementally

**Option B: Full Parity (4 weeks)**
- Implement all Phase 1 + 2 + 3
- Get to 100% parity
- Feature-complete with Claude Code
- Best-in-class coding agent

**My vote: Start with Option A (MVP).** It gives you the most critical features (context compression, checkpointing, hooks) without over-committing. You can add the remaining 10% based on actual usage patterns.

## Complete Feature Mapping: Anvil → Claude Code

### Component Score Breakdown

| Component | Current Score | Blocking 10/10 | Implementation | Effort |
|-----------|---------------|----------------|----------------|--------|
| **Agent loop** | 8/10 | Context compression, Stop hooks | Phase 1 | 3 days |
| **Tool system** | 7/10 | TodoWrite/Read, MultiEdit | Phase 2 | 2 days |
| **Tool approval** | 7/10 | File approval, Hooks, Modes | Phase 1+2 | 5 days |
| **Streaming** | 8/10 | Tool call streaming, Cancel | Phase 3 | 1 day |
| **Sub-agents** | 8/10 | Agent types, Isolation, Max 1 | Phase 3 | 3 days |
| **Sessions** | 7/10 | JSONL, Metadata, Checkpoints | Phase 1 | 3 days |

### Exact Feature Checklist for 10/10

#### Agent Loop → 10/10 Checklist

- [x] ReACT pattern
- [x] Single-threaded execution
- [x] Tool use loop
- [x] Streaming support
- [x] Max iterations
- [ ] **Context compression** (auto at 92%)
- [ ] **Stop hooks** (can force continue)
- [ ] **Message pruning** (keep recent + summary)

**Add 3 features → 10/10**

#### Tool System → 10/10 Checklist

- [x] read_file (✅ equivalent to Read)
- [x] write_file (✅ equivalent to Write)
- [x] str_replace (✅ equivalent to Edit)
- [x] grep (✅ equivalent to Grep)
- [x] glob (✅ equivalent to Glob)
- [x] list_files (✅ equivalent to LS)
- [x] run_command (⚠️ not persistent like Bash)
- [x] web_search (✅ equivalent to WebSearch)
- [x] web_extract (✅ equivalent to WebFetch)
- [ ] **TodoWrite** (planning)
- [ ] **TodoRead** (planning)
- [ ] **MultiEdit** (batch operations)
- [ ] BashOutput (optional)
- [ ] KillShell (optional)
- [ ] NotebookRead (optional)
- [ ] NotebookEdit (optional)

**Add 3 tools (Todo, MultiEdit) → 9/10**  
**Add 6 tools (all above) → 10/10**

#### Tool Approval → 10/10 Checklist

- [x] Shell command approval (CLI)
- [ ] **File write approval** (write_file)
- [ ] **File edit approval** (str_replace)
- [ ] **Permission modes** (5 modes)
- [ ] **Hook-based approval** (PreToolUse)
- [ ] **Auto-approval rules** (via hooks)
- [ ] **Diff preview** (before approval)

**Add 7 features → 10/10**

#### Streaming → 10/10 Checklist

- [x] Content streaming
- [x] Real-time output
- [ ] **Tool call streaming** (show tools as generated)
- [ ] **Cancellation** (graceful Ctrl+C)
- [ ] **Progress indicators** (per-tool)

**Add 3 features → 10/10**

#### Sub-agents → 10/10 Checklist

- [x] Can spawn sub-agents
- [x] Parallel execution (for research)
- [ ] **Agent types** (Explore, Plan, Code, Test)
- [ ] **Context isolation** (separate message history)
- [ ] **Max 1 concurrent** (for coding mode)
- [ ] **SubagentStart hook** (lifecycle)
- [ ] **SubagentStop hook** (lifecycle)

**Add 5 features → 10/10**

#### Sessions → 10/10 Checklist

- [x] Save session
- [x] Load session
- [x] Resume failed workers
- [ ] **JSONL transcript** (append-only)
- [ ] **Per-action checkpoints** (not just session-level)
- [ ] **Resume from any checkpoint**
- [ ] **Rich metadata** (tokens, iterations, tool counts)
- [ ] **Session analytics** (cost tracking, tool usage)

**Add 5 features → 10/10**

## Implementation Effort Summary

| Target | Features to Add | Total Effort | Result |
|--------|-----------------|--------------|--------|
| **MVP (90%)** | 5 features | 9.5 days | Production-ready |
| **Core (95%)** | 11 features | 14 days | Near-complete |
| **Full (100%)** | 29 features | 21 days | Exact parity |

**Your choice:**
- 🚀 Fast (2 weeks) → MVP → 90% parity
- ⚡ Balanced (3 weeks) → Core → 95% parity
- 🎯 Complete (4 weeks) → Full → 100% parity

## Implementation Dependencies

### Must Implement First (Foundation)

These are prerequisites for other features:

1. **JSONL Transcript** (1 day)
   - Required by: Resume system, Session analytics
   - Blocks: Nothing
   - **Implement immediately**

2. **Context Compression** (3 days)
   - Required by: Long sessions, Project memory
   - Blocks: Nothing
   - **Implement immediately**

3. **Hook System** (4 days)
   - Required by: All approval features, Stop control
   - Blocks: File approval, Permission modes, Stop hooks
   - **Implement after transcript + compression**

### Can Implement Independently (Parallel)

These don't depend on others:

4. **Todo Tools** (1 day) - Independent
5. **Project Memory** (2 days) - Depends on compression
6. **Permission Modes** (1 day) - Depends on hooks
7. **File Approval** (0.5 day) - Depends on hooks
8. **Agent Types** (2 days) - Independent
9. **MultiEdit** (1 day) - Independent

### Recommended Implementation Order

**Week 1:**
1. JSONL Transcript (1 day)
2. Context Compression (3 days)
3. Todo Tools (1 day)

**Week 2:**
4. Hook System (4 days)
5. Project Memory (2 days - parallel with hooks)

**Week 3 (if doing full parity):**
6. Permission Modes (1 day)
7. File Approval (0.5 day)
8. Stop Control (1 day)
9. Agent Types (2 days)
10. MultiEdit (1 day)

This order maximizes parallelization and ensures no feature blocks another.

## Recommended Approach

1. **Implement Phase 1 (context + memory + todos)** - Most impact
2. **Test with real coding tasks** - Validate improvements
3. **Add Phase 2 if needed** - Based on usage patterns
4. **Keep Phase 3 as optional** - Not critical path

Your core is already excellent. These additions bring you to Claude Code parity without over-engineering.

## Detailed Roadmap to 10/10 on Each Component

### Agent Loop: 8/10 → 10/10

**Currently at 8/10 because:**
- ✅ Core ReACT loop works perfectly
- ✅ Streaming implemented
- ❌ No context compression
- ❌ No stop control

**To reach 10/10, add:**
1. Context compression (auto at 92%)
2. Stop hooks (prevent premature exit)
3. Message pruning (keep recent + summary)

**Effort:** 3 days  
**Result:** Unlimited session length, smarter stopping

---

### Tool System: 7/10 → 10/10

**Currently at 7/10 because:**
- ✅ Basic file ops work (read, write, edit)
- ✅ Basic search works (grep, glob)
- ❌ Missing 16 tools Claude Code has
- ❌ No planning tools (Todo)
- ❌ No batch operations (MultiEdit)

**To reach 10/10, add:**
| Priority | Tool | Effort | Impact |
|----------|------|--------|--------|
| Critical | TodoWrite/Read | 1 day | High |
| High | MultiEdit | 1 day | Medium |
| Medium | BashOutput | 0.5 day | Low |
| Medium | KillShell | 0.5 day | Low |
| Low | NotebookRead/Edit | 1 day | Low |

**Minimum to reach 10/10:** TodoWrite/Read + MultiEdit (2 days)  
**Full parity:** All tools (4 days)

---

### Tool Approval: 7/10 → 10/10

**Currently at 7/10 because:**
- ✅ Shell commands require approval
- ❌ File operations auto-approved (dangerous)
- ❌ No permission modes
- ❌ No hook-based approval
- ❌ No auto-approval rules

**To reach 10/10, add:**
1. **File operation approval** (0.5 day)
   - Require approval for write_file
   - Require approval for str_replace
   - Show diff preview

2. **Permission modes** (1 day)
   - default, plan, accept_edits, dont_ask, bypass
   - CLI flag: `--permission-mode`

3. **Hook-based approval** (included in hook system)
   - PreToolUse hooks
   - Custom auto-approval rules
   - Per-project configuration

**Effort:** 1.5 days (+ 3 days for hooks)  
**Result:** Fine-grained control, safer execution

---

### Streaming: 8/10 → 10/10

**Currently at 8/10 because:**
- ✅ Content streaming works
- ✅ Real-time output
- ❌ Tool calls don't stream (appear all at once)
- ❌ No cancellation support
- ❌ No per-tool progress

**To reach 10/10, add:**
1. **Tool call streaming**
   ```
   Before: [Wait...] "Calling read_file, grep, edit_file"
   After:  "Calling read_file..." → "Calling grep..." → "Calling edit_file..."
   ```

2. **Cancellation support**
   - Ctrl+C during LLM call → gracefully stop
   - Ctrl+C during tool execution → ask to confirm

3. **Tool progress indicators**
   ```
   [●●●○○] read_file: Reading main.py (45%)
   [●●●●●] grep: Searching... done
   ```

**Effort:** 1-2 days  
**Result:** Better UX, responsive controls

---

### Sub-agents: 8/10 → 10/10

**Currently at 8/10 because:**
- ✅ SubagentRunner works
- ✅ Can spawn multiple workers
- ❌ No specialized agent types
- ❌ No context isolation
- ❌ No max 1 concurrent for coding
- ❌ No SubagentStart/Stop hooks

**To reach 10/10, add:**
1. **Agent types** (2 days)
   - Explore (read-only, fast exploration)
   - Plan (planning only, no execution)
   - Code (implementation)
   - Test (testing focus)

2. **Context isolation** (1 day)
   - Each sub-agent has separate message history
   - Sub-agent can't see parent's messages
   - Results returned to parent

3. **Max 1 concurrent for coding** (0.5 day)
   - Enforce sequentially for coding mode
   - Keep parallel for research mode

4. **Sub-agent lifecycle hooks** (included in hook system)
   - SubagentStart
   - SubagentStop

**Effort:** 3-4 days  
**Result:** Specialized agents, cleaner separation

---

### Sessions: 7/10 → 10/10

**Currently at 7/10 because:**
- ✅ Save/load works
- ✅ Resume failed workers
- ❌ No per-action checkpoints
- ❌ No JSONL format
- ❌ Limited metadata (no tokens, iterations, tool counts)
- ❌ Can't resume from arbitrary point

**To reach 10/10, add:**
1. **JSONL transcript** (1 day) - Append-only, per-action
2. **Rich metadata** (0.5 day) - Track tokens, tools, iterations
3. **Resume from checkpoint** (1 day) - Load from line N in JSONL
4. **Session analytics** (0.5 day) - Tool usage stats, cost tracking

**Effort:** 3 days  
**Result:** Production-grade session management

---

## Exact Feature Parity Checklist

### Core Loop ✅ → ⭐⭐⭐
- [x] ReACT pattern (Reason + Act)
- [x] Sequential tool execution
- [x] Max iterations control
- [ ] **Context compression** ← CRITICAL
- [ ] **Stop hooks** ← HIGH
- [ ] Message pruning

### Tools ⚠️ → ⭐⭐⭐
- [x] File ops (read, write, edit)
- [x] Search (grep, glob, ls)
- [x] Execution (bash/run_command)
- [ ] **TodoWrite/Read** ← CRITICAL
- [ ] **MultiEdit** ← HIGH
- [ ] BashOutput, KillShell (optional)
- [ ] NotebookRead/Edit (optional)

### Control & Safety ⚠️ → ⭐⭐⭐
- [x] Shell command approval
- [ ] **File operation approval** ← CRITICAL
- [ ] **Permission modes** ← HIGH
- [ ] **Hook system (10 events)** ← CRITICAL
- [ ] Auto-approval rules

### Memory & Context ❌ → ⭐⭐⭐
- [x] Session save/load
- [ ] **Context compression** ← CRITICAL
- [ ] **MEMORY.md file** ← HIGH
- [ ] **JSONL transcript** ← HIGH
- [ ] Auto-summarization

### Advanced ⚠️ → ⭐
- [x] Sub-agents (generic)
- [ ] **Specialized agent types** ← MEDIUM
- [ ] **Context isolation** ← MEDIUM
- [ ] Diff preview (optional)
- [ ] Persistent shell (optional)

## Critical Path to Production Parity

If you implement ONLY these 5 features:

1. **Context compression** (3 days) ⭐⭐⭐
2. **JSONL transcript** (1 day) ⭐⭐⭐
3. **Hook system** (4 days) ⭐⭐⭐
4. **Todo tools** (1 day) ⭐⭐
5. **File approval** (0.5 day) ⭐⭐

**Total: 9.5 days (2 weeks)**

You'll have:
- Agent loop: 8/10 → 10/10 ✅
- Tool system: 7/10 → 9/10 ✅
- Tool approval: 7/10 → 9/10 ✅
- Sessions: 7/10 → 9/10 ✅

**This gets you to 90-95% Claude Code parity with the highest-impact features.**
