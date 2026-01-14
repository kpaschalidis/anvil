import os
from pathlib import Path
from typing import Dict

from common.text_template import render_template


def load_prompt_blocks(
    prompt_block_dirs: list[Path] | None = None,
) -> Dict[str, Dict[str, str] | str]:
    if prompt_block_dirs is None:
        prompt_block_dirs = [Path(__file__).resolve().parent / "blocks"]

    def find_block(relative_path: str) -> str:
        for directory in prompt_block_dirs:
            path = directory / relative_path
            if path.exists():
                return path.read_text(encoding="utf-8")
        return ""

    tool_path_overrides = {
        "apply_edit": "tools/edit.md",
        "run_command": "tools/bash.md",
        "list_files": "tools/glob.md",
    }

    def tool_description(tool_name: str) -> str:
        rel = tool_path_overrides.get(tool_name, f"tools/{tool_name}.md")
        return find_block(rel)

    return {
        "main": find_block("system.md"),
        "tool_descriptions": {
            "read_file": tool_description("readfile"),
            "apply_edit": tool_description("apply_edit"),
            "write_file": tool_description("write"),
            "run_command": tool_description("run_command"),
            "list_files": tool_description("list_files"),
            "grep": tool_description("grep"),
            "skill": tool_description("skill"),
            "task": tool_description("task"),
        },
        "agent_prompts": {
            "task": find_block("agents/task.md"),
            "explore": find_block("agents/explore.md"),
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
