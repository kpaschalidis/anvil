from scout.extraction.prompts.extract_v1 import EXTRACTION_PROMPT_V1
from scout.extraction.prompts.extract_v2 import EXTRACTION_PROMPT_V2

DEFAULT_EXTRACTION_PROMPT_VERSION = "v1"

EXTRACTION_PROMPTS = {
    "v1": EXTRACTION_PROMPT_V1,
    "v2": EXTRACTION_PROMPT_V2,
}


def get_extraction_prompt(version: str) -> str:
    if version not in EXTRACTION_PROMPTS:
        raise ValueError(f"Unknown extraction prompt version: {version}")
    return EXTRACTION_PROMPTS[version]


__all__ = [
    "DEFAULT_EXTRACTION_PROMPT_VERSION",
    "EXTRACTION_PROMPTS",
    "get_extraction_prompt",
]

