from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any

import yaml


@dataclass(frozen=True)
class MarkdownEntry:
    name: str
    path: Path
    body: str
    frontmatter: Dict[str, Any]


def _parse_frontmatter(text: str) -> tuple[Dict[str, Any], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text

    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            header = "\n".join(lines[1:idx])
            body = "\n".join(lines[idx + 1 :]).lstrip()
            data = yaml.safe_load(header) or {}
            return data, body

    return {}, text


def _compute_name(base_dir: Path, path: Path) -> str:
    relative = path.relative_to(base_dir).with_suffix("")
    return ":".join(relative.parts)


class MarkdownIndex:
    def __init__(self, root_path: str | Path):
        self.root_path = Path(root_path)
        self.commands: Dict[str, MarkdownEntry] = {}
        self.skills: Dict[str, MarkdownEntry] = {}

    def reload(self) -> None:
        self.commands = self._load_entries(self.root_path / ".anvil" / "commands")
        self.skills = self._load_entries(self.root_path / ".anvil" / "skills")

    def _load_entries(self, base_dir: Path) -> Dict[str, MarkdownEntry]:
        entries: Dict[str, MarkdownEntry] = {}
        if not base_dir.exists():
            return entries
        for path in base_dir.rglob("*.md"):
            text = path.read_text(encoding="utf-8")
            frontmatter, body = _parse_frontmatter(text)
            name = _compute_name(base_dir, path)
            entries[name] = MarkdownEntry(
                name=name, path=path, body=body, frontmatter=frontmatter
            )
        return entries
