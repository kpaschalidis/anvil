from pathlib import Path


def render_template(
    text: str,
    arguments: str | None = None,
    root_path: str | Path | None = None,
    cwd: str | Path | None = None,
) -> str:
    rendered = text.replace("$ARGUMENTS", arguments or "")
    if root_path is not None:
        rendered = rendered.replace("${root_path}", str(root_path))
    if cwd is not None:
        rendered = rendered.replace("${cwd}", str(cwd))
    return rendered
