import os
from pathlib import Path
from typing import Dict

from common.text_template import render_template


def load_prompt_blocks() -> Dict[str, Dict[str, str] | str]:
    base = Path(__file__).resolve().parent / "blocks"

    def read_block(filename: str) -> str:
        path = base / filename
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    return {
        "main": read_block("system.md"),
        "tool_descriptions": {
            "read_file": read_block("tools/readfile.md"),
            "apply_edit": read_block("tools/edit.md"),
            "write_file": read_block("tools/write.md"),
            "run_command": read_block("tools/bash.md"),
            "list_files": read_block("tools/glob.md"),
            "grep": read_block("tools/grep.md"),
            "skill": read_block("tools/skill.md"),
            "task": read_block("tools/task.md"),
        },
        "agent_prompts": {
            "task": read_block("agents/task.md"),
            "explore": read_block("agents/explore.md"),
        },
    }


def build_main_system_prompt(
    root_path: str | Path,
    tool_names: list[str],
    memory_text: str | None,
    vendored_blocks: Dict[str, Dict[str, str] | str],
) -> str:
    parts: list[str] = []
    main_prompt = vendored_blocks.get("main", "")
    if main_prompt:
        parts.append(main_prompt)

    tool_descs = vendored_blocks.get("tool_descriptions", {})
    for name in tool_names:
        block = tool_descs.get(name)
        if block:
            parts.append(block)

    if memory_text:
        parts.append("# Project Memory (ANVIL.md)\n" + memory_text.strip())

    tool_inventory = "# Tool Inventory\n" + "\n".join(
        f"- {name}" for name in tool_names
    )
    parts.append(tool_inventory)

    combined = "\n\n".join(part.strip() for part in parts if part.strip())
    return render_template(
        combined,
        root_path=root_path,
        cwd=os.getcwd(),
    )
