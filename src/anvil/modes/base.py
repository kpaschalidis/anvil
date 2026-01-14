from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from anvil.config import AgentConfig
    from anvil.tools import ToolRegistry
    from anvil.runtime.builtins import BuiltinCommands
    from anvil.runtime.runtime import AnvilRuntime


@dataclass
class ModeConfig:
    name: str
    description: str
    session_namespace: str = "default"
    apply_defaults: Callable[[AgentConfig], AgentConfig] | None = None
    register_tools: Callable[[ToolRegistry, AnvilRuntime], None] | None = None
    prompt_block_dirs: list[Path] = field(default_factory=list)
    extend_builtins: Callable[[BuiltinCommands, AnvilRuntime], None] | None = None
