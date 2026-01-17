import json
import os
from pathlib import Path
from typing import Any, Dict

from common.text_template import render_template
from anvil.history import MessageHistory
from anvil.subagents.registry import AgentRegistry, AgentDefinition
from anvil.subagents.trace import SubagentTrace, ToolCallRecord


class SubagentRunner:
    def __init__(
        self,
        root_path: str | Path,
        agent_registry: AgentRegistry,
        tool_registry,
        vendored_prompts: Dict[str, Dict[str, str] | str],
        completion_fn,
        default_model: str,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ):
        self.root_path = Path(root_path)
        self.agent_registry = agent_registry
        self.tool_registry = tool_registry
        self.vendored_prompts = vendored_prompts
        self.completion_fn = completion_fn
        self.default_model = default_model
        self.temperature = temperature
        self.max_tokens = max_tokens

    def _build_system_prompt(self, agent_def: AgentDefinition | None) -> str:
        agent_prompts = self.vendored_prompts.get("agent_prompts", {})
        parts = [
            agent_prompts.get("task", ""),
            agent_prompts.get("explore", ""),
            agent_def.body if agent_def else "",
        ]
        combined = "\n\n".join(part.strip() for part in parts if part.strip())
        return render_template(
            combined,
            root_path=self.root_path,
            cwd=os.getcwd(),
        )

    def run_task(
        self,
        prompt: str,
        agent_name: str | None = None,
        model: str | None = None,
        max_iterations: int = 6,
        *,
        allowed_tool_names: set[str] | None = None,
        max_web_search_calls: int | None = None,
    ) -> str:
        output, _trace = self.run_task_with_trace(
            prompt=prompt,
            agent_name=agent_name,
            model=model,
            max_iterations=max_iterations,
            allowed_tool_names=allowed_tool_names,
            max_web_search_calls=max_web_search_calls,
        )
        return output

    def run_task_with_trace(
        self,
        *,
        prompt: str,
        agent_name: str | None = None,
        model: str | None = None,
        max_iterations: int = 6,
        allowed_tool_names: set[str] | None = None,
        max_web_search_calls: int | None = None,
    ) -> tuple[str, SubagentTrace]:
        agent_def = None
        if agent_name:
            agent_def = self.agent_registry.agents.get(agent_name)

        trace = SubagentTrace()

        history = MessageHistory()
        history.set_system_prompt(self._build_system_prompt(agent_def))
        history.add_user_message(prompt)

        messages = history.get_messages_for_api()
        iterations = 0
        tools = self.tool_registry.get_tool_schemas()
        if allowed_tool_names is not None:
            tools = [t for t in tools if t.get("function", {}).get("name") in allowed_tool_names]

        while iterations < max_iterations:
            iterations += 1
            response = self.completion_fn(
                model=model or (agent_def.model if agent_def else None) or self.default_model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            response_msg = response.choices[0].message

            if hasattr(response_msg, "tool_calls") and response_msg.tool_calls:
                tool_calls = response_msg.tool_calls
                history.add_assistant_message(
                    content=response_msg.content,
                    tool_calls=[
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
                )

                for tool_call in tool_calls:
                    tool_name = tool_call.function.name
                    tool_args = json.loads(tool_call.function.arguments)
                    if allowed_tool_names is not None and tool_name not in allowed_tool_names:
                        result = {
                            "success": False,
                            "error": f"Tool not allowed in worker mode: {tool_name}",
                        }
                    elif (
                        tool_name == "web_search"
                        and max_web_search_calls is not None
                        and trace.web_search_calls >= int(max_web_search_calls)
                    ):
                        result = {
                            "success": False,
                            "error": f"Max web_search calls reached ({max_web_search_calls})",
                        }
                    else:
                        result = self.tool_registry.execute_tool(tool_name, tool_args)

                    trace.tool_calls.append(
                        ToolCallRecord(tool_name=tool_name, args=tool_args, result=result)
                    )
                    if tool_name == "web_search":
                        trace.web_search_calls += 1
                        trace.citations.update(_extract_citations_from_web_search_result(result))
                        trace.sources.update(_extract_source_metadata_from_web_search_result(result))

                    history.add_tool_result(
                        tool_call_id=tool_call.id,
                        name=tool_name,
                        result=json.dumps(result),
                    )

                messages = history.get_messages_for_api()
                continue

            if response_msg.content:
                history.add_assistant_message(content=response_msg.content)
                return response_msg.content, trace

            return "", trace

        return "Subagent exceeded max iterations without a final response.", trace


class TaskTool:
    def __init__(self, runner: SubagentRunner):
        self.runner = runner

    def __call__(self, prompt: str, agent: str | None = None, subagent_type: str | None = None):
        return self.runner.run_task(prompt, agent_name=agent or subagent_type)


def _extract_citations_from_web_search_result(result: dict[str, Any]) -> set[str]:
    citations: set[str] = set()
    if not isinstance(result, dict):
        return citations

    if result.get("success") is not True:
        return citations

    payload = result.get("result")
    if not isinstance(payload, dict):
        return citations

    items = payload.get("results")
    if not isinstance(items, list):
        return citations

    for item in items:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        if isinstance(url, str) and url.startswith("http"):
            citations.add(url)

    return citations


def _extract_source_metadata_from_web_search_result(result: dict[str, Any]) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    if not isinstance(result, dict):
        return out
    if result.get("success") is not True:
        return out
    payload = result.get("result")
    if not isinstance(payload, dict):
        return out
    items = payload.get("results")
    if not isinstance(items, list):
        return out

    for item in items:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        if not (isinstance(url, str) and url.startswith("http")):
            continue
        title = item.get("title")
        snippet = item.get("content") or item.get("snippet") or item.get("description")
        meta: dict[str, str] = {}
        if isinstance(title, str) and title.strip():
            meta["title"] = title.strip()
        if isinstance(snippet, str) and snippet.strip():
            meta["snippet"] = snippet.strip()
        if meta:
            out[url] = meta
    return out
