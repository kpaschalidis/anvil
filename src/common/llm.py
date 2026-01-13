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


def completion_with_usage(
    model: str,
    messages: list[dict],
    stream: bool = False,
    tools: list[dict] | None = None,
    tool_choice: str | None = None,
    temperature: float = 0.0,
    max_tokens: int = 4096,
    **kwargs,
) -> tuple[Any, dict]:
    response = completion(
        model=model,
        messages=messages,
        stream=stream,
        tools=tools,
        tool_choice=tool_choice,
        temperature=temperature,
        max_tokens=max_tokens,
        **kwargs,
    )

    usage = getattr(response, "usage", None)
    try:
        cost_usd = float(litellm.completion_cost(response) or 0.0)
    except Exception:
        cost_usd = 0.0
    usage_dict = {
        "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
        "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
        "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
        "cost_usd": cost_usd,
    }
    return response, usage_dict


def get_model_info(model: str) -> dict:
    try:
        return litellm.get_model_info(model)
    except Exception:
        return {}


def supports_tools(model: str) -> bool:
    info = get_model_info(model)
    return info.get("supports_function_calling", False)
