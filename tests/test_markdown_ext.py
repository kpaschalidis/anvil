from pathlib import Path

from anvil.ext.markdown_executor import render_markdown_body
from anvil.ext.markdown_loader import MarkdownIndex


def test_markdown_loader_names(tmp_path: Path):
    commands_dir = tmp_path / ".anvil" / "commands"
    tools_dir = commands_dir / "tools"
    tools_dir.mkdir(parents=True)

    (commands_dir / "foo.md").write_text("hello", encoding="utf-8")
    (tools_dir / "bar.md").write_text("world", encoding="utf-8")

    index = MarkdownIndex(tmp_path)
    index.reload()

    assert "foo" in index.commands
    assert "tools:bar" in index.commands


def test_markdown_arguments_substitution():
    body = "Run this: $ARGUMENTS"
    rendered = render_markdown_body(body, "tests", root_path=".")
    assert rendered == "Run this: tests"
