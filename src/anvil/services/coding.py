from __future__ import annotations

from dataclasses import dataclass

from anvil.config import AgentConfig, resolve_model_alias
from anvil.modes.registry import get_mode
from anvil.runtime.runtime import AnvilRuntime


@dataclass(frozen=True, slots=True)
class CodingConfig:
    root_path: str
    model: str = "gpt-4o"
    max_iterations: int = 10
    mode: str = "coding"


@dataclass(frozen=True, slots=True)
class CodingResult:
    final_response: str


class CodingService:
    def __init__(self, config: CodingConfig):
        self.config = config

    def run(self, *, prompt: str, files: list[str] | None = None) -> CodingResult:
        cfg = AgentConfig(
            model=resolve_model_alias(self.config.model),
            stream=False,
            use_tools=True,
        )
        runtime = AnvilRuntime(
            self.config.root_path,
            cfg,
            mode=get_mode(self.config.mode),
        )
        final_response = runtime.run_prompt(
            prompt,
            files=files,
            max_iterations=self.config.max_iterations,
        )
        return CodingResult(final_response=final_response)

