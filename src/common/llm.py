import warnings
from typing import Any

import litellm
from litellm import completion as litellm_completion

warnings.filterwarnings("ignore", message="Pydantic serializer warnings")
litellm.drop_params = True


def completion(
    model: str,
    messages: list[dict],
    stream: bool = False,
    tools: list[dict] | None = None,
    tool_choice: str | None = None,
    temperature: float = 0.0,
    max_tokens: int = 4096,
    **kwargs,
) -> Any:
    params = {
        "model": model,
        "messages": messages,
        "stream": stream,
        "temperature": temperature,
        "max_tokens": max_tokens,
        **kwargs,
    }

    if tools:
        params["tools"] = tools
        params["tool_choice"] = tool_choice or "auto"

    return litellm_completion(**params)


def get_model_info(model: str) -> dict:
    try:
        return litellm.get_model_info(model)
    except Exception:
        return {}


def supports_tools(model: str) -> bool:
    info = get_model_info(model)
    return info.get("supports_function_calling", False)
