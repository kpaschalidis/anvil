def register_coding_tools(tools, runtime) -> None:
    ext = runtime.extensions["coding"]

    tools.register_tool(
        name="git_status",
        description="Get the current git status",
        parameters={"type": "object", "properties": {}, "required": []},
        implementation=lambda: ext.git.get_status() or "Nothing to commit",
    )

    tools.register_tool(
        name="git_diff",
        description="Get the current git diff",
        parameters={"type": "object", "properties": {}, "required": []},
        implementation=lambda: ext.git.get_diff() or "No changes",
    )

    def tool_apply_edit(filepath: str, search: str, replace: str) -> str:
        if runtime.config.dry_run:
            return f"[DRY RUN] Would edit {filepath}"

        success = runtime.files.apply_edit(filepath, search, replace)
        if success:
            runtime.hooks.fire_files_changed([filepath], "apply_edit")
            return f"Edit applied successfully to {filepath}"
        return f"Failed to apply edit to {filepath} - search block not found"

    tools.register_tool(
        name="apply_edit",
        description="Apply a search and replace edit to a file",
        parameters={
            "type": "object",
            "properties": {
                "filepath": {"type": "string", "description": "Path to the file"},
                "search": {"type": "string", "description": "Text to search for"},
                "replace": {"type": "string", "description": "Text to replace with"},
            },
            "required": ["filepath", "search", "replace"],
        },
        implementation=tool_apply_edit,
    )
