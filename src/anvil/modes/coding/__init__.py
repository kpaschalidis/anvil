from anvil.config import AgentConfig
from anvil.modes.base import ModeConfig


def apply_coding_defaults(config: AgentConfig) -> AgentConfig:
    config.auto_lint = True
    config.auto_commit = True
    return config


CodingMode = ModeConfig(
    name="coding",
    description="AI coding assistant with file editing and git integration",
    session_namespace="coding",
    apply_defaults=apply_coding_defaults,
)

