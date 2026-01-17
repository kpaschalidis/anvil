from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from common import llm
from common.events import (
    AssistantDeltaEvent,
    AssistantMessageEvent,
    AssistantResponseStartEvent,
    EventEmitter,
    ToolCallEvent,
    ToolResultEvent,
)


@dataclass(frozen=True, slots=True)
class LoopConfig:
    model: str
    system_prompt: str | None = None
    max_iterations: int = 10
    temperature: float = 0.0
    max_tokens: int = 4096
    stream: bool = True
    use_tools: bool = True


@dataclass(frozen=True, slots=True)
class LoopResult:
    iterations: int
    final_response: str


def _stream_to_message(
    *,
    model: str,
    messages: list[dict],
    temperature: float,
    max_tokens: int,
    tools: list[dict] | None,
    emitter: EventEmitter | None,
) -> Any:
    stream = llm.completion(
        model=model,
        messages=messages,
        stream=True,
        tools=tools,
        tool_choice="auto" if tools else None,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    accumulated_content = ""
    accumulated_tool_calls: dict[int, dict[str, Any]] = {}

    for chunk in stream:
        delta = chunk.choices[0].delta

        if hasattr(delta, "content") and delta.content:
            content = delta.content
            accumulated_content += content
            if emitter is not None:
                emitter.emit(AssistantDeltaEvent(text=content))

        if hasattr(delta, "tool_calls") and delta.tool_calls:
            for tc in delta.tool_calls:
                idx = tc.index

                if idx not in accumulated_tool_calls:
                    accumulated_tool_calls[idx] = {
                        "id": "",
                        "type": "function",
                        "function": {"name": "", "arguments": ""},
                    }

                if tc.id:
                    accumulated_tool_calls[idx]["id"] = tc.id
                if hasattr(tc, "function") and tc.function:
                    if tc.function.name:
                        accumulated_tool_calls[idx]["function"]["name"] = tc.function.name
                    if tc.function.arguments:
                        accumulated_tool_calls[idx]["function"]["arguments"] += tc.function.arguments

    class Response:
        def __init__(self, content: str, tool_calls: dict[int, dict[str, Any]]):
            self.content = content
            self.tool_calls: list[Any] = []

            for tc_data in tool_calls.values():

                class ToolCall:
                    def __init__(self, data: dict[str, Any]):
                        self.id = data["id"]
                        self.type = data["type"]

                        class Function:
                            def __init__(self, func_data: dict[str, Any]):
                                self.name = func_data["name"]
                                self.arguments = func_data["arguments"]

                        self.function = Function(data["function"])

                self.tool_calls.append(ToolCall(tc_data))

    return Response(accumulated_content, accumulated_tool_calls)


def run_loop(
    messages: list[dict],
    tools: list[dict],
    execute_tool: Callable[[str, dict], Any],
    config: LoopConfig,
    emitter: EventEmitter | None = None,
) -> LoopResult:
    final_response = ""
    tools_arg = tools if (config.use_tools and tools) else None
    iteration = 0

    for iteration in range(1, config.max_iterations + 1):
        api_messages = (
            ([{"role": "system", "content": config.system_prompt}] if config.system_prompt else [])
            + messages
        )

        if emitter is not None:
            emitter.emit(AssistantResponseStartEvent(iteration=iteration))

        if config.stream:
            response = _stream_to_message(
                model=config.model,
                messages=api_messages,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
                tools=tools_arg,
                emitter=emitter,
            )
        else:
            completion = llm.completion(
                model=config.model,
                messages=api_messages,
                stream=False,
                tools=tools_arg,
                tool_choice="auto" if tools_arg else None,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
            )
            response = completion.choices[0].message

        tool_calls = getattr(response, "tool_calls", None) or []
        if tool_calls:
            messages.append(
                {
                    "role": "assistant",
                    "content": response.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in tool_calls
                    ],
                }
            )

            for tool_call in tool_calls:
                tool_name = tool_call.function.name
                tool_args = json.loads(tool_call.function.arguments)
                if emitter is not None:
                    emitter.emit(
                        ToolCallEvent(
                            tool_call_id=tool_call.id,
                            tool_name=tool_name,
                            args=tool_args,
                        )
                    )

                result = execute_tool(tool_name, tool_args)
                if emitter is not None:
                    emitter.emit(
                        ToolResultEvent(
                            tool_call_id=tool_call.id,
                            tool_name=tool_name,
                            result=result,
                        )
                    )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_name,
                        "content": json.dumps(result),
                    }
                )

            continue

        if response.content:
            final_response = response.content
            messages.append({"role": "assistant", "content": response.content})
            if emitter is not None:
                emitter.emit(AssistantMessageEvent(content=response.content))
        break

    return LoopResult(iterations=iteration, final_response=final_response)
