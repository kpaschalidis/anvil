from dataclasses import dataclass


MODEL_ALIASES = {
    "sonnet": "claude-sonnet-4-20250514",
    "opus": "claude-opus-4-20250514",
    "haiku": "claude-3-5-haiku-20241022",
    "4o": "gpt-4o",
    "4": "gpt-4-turbo",
    "flash": "gemini/gemini-2.5-flash",
    "deepseek": "deepseek/deepseek-chat",
}


def resolve_model_alias(name: str) -> str:
    return MODEL_ALIASES.get(name.lower(), name)


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
    auto_lint: bool = True
    lint_fix_retries: int = 2
