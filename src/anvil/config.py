from dataclasses import dataclass


@dataclass
class AgentConfig:
    model: str = "gpt-4o"
    temperature: float = 0.0
    max_tokens: int = 4096
    auto_commit: bool = True
    dry_run: bool = False
    max_retries: int = 3
    stream: bool = True
    use_tools: bool = True
