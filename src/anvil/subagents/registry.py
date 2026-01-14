from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any

import yaml


@dataclass(frozen=True)
class AgentDefinition:
    name: str
    path: Path
    body: str
    frontmatter: Dict[str, Any]
    description: str | None
    model: str | None


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


class AgentRegistry:
    def __init__(self, root_path: str | Path):
        self.root_path = Path(root_path)
        self.agents: Dict[str, AgentDefinition] = {}

    def reload(self) -> None:
        base_dir = self.root_path / ".anvil" / "agents"
        agents: Dict[str, AgentDefinition] = {}
        if base_dir.exists():
            for path in base_dir.rglob("*.md"):
                text = path.read_text(encoding="utf-8")
                frontmatter, body = _parse_frontmatter(text)
                name = frontmatter.get("name") or _compute_name(base_dir, path)
                agents[name] = AgentDefinition(
                    name=name,
                    path=path,
                    body=body,
                    frontmatter=frontmatter,
                    description=frontmatter.get("description"),
                    model=frontmatter.get("model"),
                )
        self.agents = agents
