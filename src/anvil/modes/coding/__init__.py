from pathlib import Path

from anvil.config import AgentConfig
from anvil.modes.base import ModeConfig
from anvil.modes.coding.builtins import extend_coding_builtins
from anvil.modes.coding.extension import CodingExtension
from anvil.modes.coding.tools import register_coding_tools


def apply_coding_defaults(config: AgentConfig) -> AgentConfig:
    config.auto_lint = True
    config.auto_commit = True
    return config


def setup_coding_mode(tools, runtime) -> None:
    ext = CodingExtension(runtime)
    runtime.extensions["coding"] = ext
    runtime.hooks.on_files_changed.append(ext.on_files_changed)
    runtime.hooks.on_assistant_message.append(ext.on_assistant_message)
    register_coding_tools(tools, runtime)


CodingMode = ModeConfig(
    name="coding",
    description="AI coding assistant with file editing and git integration",
    session_namespace="coding",
    apply_defaults=apply_coding_defaults,
    register_tools=setup_coding_mode,
    extend_builtins=extend_coding_builtins,
    prompt_block_dirs=[Path(__file__).parent / "prompts"],
)
