from typing import List, Dict, Any, Optional


class MessageHistory:
    def __init__(self):
        self.messages: List[Dict[str, Any]] = []
        self.system_prompt: Optional[str] = None

    def set_system_prompt(self, prompt: str):
        self.system_prompt = prompt

    def add_user_message(self, content: str):
        self.messages.append({"role": "user", "content": content})

    def add_assistant_message(
        self, content: Optional[str] = None, tool_calls: Optional[List[Dict]] = None
    ):
        message: Dict[str, Any] = {"role": "assistant"}

        if content:
            message["content"] = content

        if tool_calls:
            message["tool_calls"] = tool_calls

        self.messages.append(message)

    def add_tool_result(self, tool_call_id: str, name: str, result: str):
        self.messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "name": name,
                "content": result,
            }
        )

    def get_messages_for_api(self) -> List[Dict[str, Any]]:
        if self.system_prompt:
            return [{"role": "system", "content": self.system_prompt}] + self.messages
        return self.messages

    def clear(self):
        self.messages = []
