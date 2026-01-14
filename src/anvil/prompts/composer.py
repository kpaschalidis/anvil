import os
from pathlib import Path
from typing import Callable, Dict

from common.text_template import render_template

TOOL_PATH_OVERRIDES = {
    "read_file": "tools/readfile.md",
    "write_file": "tools/write.md",
    "run_command": "tools/bash.md",
    "list_files": "tools/glob.md",
}


def load_prompt_blocks(
    prompt_block_dirs: list[Path] | None = None,
) -> Dict[str, Callable[[str], str] | str | Dict[str, str]]:
    if prompt_block_dirs is None:
        prompt_block_dirs = [Path(__file__).resolve().parent / "blocks"]

    def find_block(relative_path: str) -> str:
        for directory in prompt_block_dirs:
            path = directory / relative_path
            if path.exists():
                return path.read_text(encoding="utf-8")
        return ""

    def get_tool_description(tool_name: str) -> str:
        rel = TOOL_PATH_OVERRIDES.get(tool_name, f"tools/{tool_name}.md")
        return find_block(rel)

    return {
        "main": find_block("system.md"),
        "get_tool_description": get_tool_description,
        "agent_prompts": {
            "task": find_block("agents/task.md"),
            "explore": find_block("agents/explore.md"),
        },
    }


def build_main_system_prompt(
    root_path: str | Path,
    tool_names: list[str],
    memory_text: str | None,
    vendored_blocks: Dict[str, Callable[[str], str] | str | Dict[str, str]],
) -> str:
    parts: list[str] = []
    main_prompt = vendored_blocks.get("main", "")
    if main_prompt:
        parts.append(main_prompt)

    get_tool_desc = vendored_blocks.get("get_tool_description")
    if get_tool_desc and callable(get_tool_desc):
        for name in tool_names:
            block = get_tool_desc(name)
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
