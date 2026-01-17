from anvil.modes.base import ModeConfig
from anvil.modes.coding import CodingMode

MODES: dict[str, ModeConfig] = {
    "coding": CodingMode,
}


def list_modes() -> list[str]:
    return sorted(MODES.keys())


def get_mode(name: str) -> ModeConfig:
    if name not in MODES:
        available = ", ".join(list_modes())
        raise ValueError(f"Unknown mode: {name}. Available: {available}")
    return MODES[name]
