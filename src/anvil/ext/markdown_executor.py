import os
from pathlib import Path

from common.text_template import render_template
from anvil.ext.markdown_loader import MarkdownEntry


def render_markdown_body(
    body: str,
    arguments: str,
    root_path: str | Path,
    cwd: str | Path | None = None,
) -> str:
    return render_template(
        body,
        arguments=arguments,
        root_path=root_path,
        cwd=cwd or os.getcwd(),
    )


class MarkdownExecutor:
    def __init__(self, root_path: str | Path, history, send_loop):
        self.root_path = Path(root_path)
        self.history = history
        self.send_loop = send_loop

    def execute(self, entry: MarkdownEntry, arguments: str) -> None:
        rendered = render_markdown_body(
            entry.body, arguments=arguments, root_path=self.root_path
        )
        self.history.add_user_message(rendered)
        self.send_loop()
