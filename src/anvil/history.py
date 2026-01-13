from typing import List, Dict, Any, Optional


class MessageHistory:
    def __init__(self):
        self.messages: List[Dict[str, Any]] = []
        self.system_prompt: Optional[str] = None
        self.summary: Optional[str] = None

    def set_system_prompt(self, prompt: str):
        self.system_prompt = prompt

    def set_summary(self, summary: Optional[str]):
        self.summary = summary

    def add_example_messages(self, examples: List[Dict[str, Any]]):
        self.messages = list(examples) + self.messages

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

    def get_messages_for_api(self, system_reminder: Optional[str] = None) -> List[Dict[str, Any]]:
        msgs: List[Dict[str, Any]] = []
        if self.system_prompt:
            msgs.append({"role": "system", "content": self.system_prompt})
        if self.summary:
            msgs.append({"role": "system", "content": f"Conversation summary:\n{self.summary}"})
        msgs.extend(self.messages)
        
        if system_reminder:
            msgs.append({"role": "system", "content": system_reminder})
        
        return msgs

    def clear(self):
        self.messages = []
        self.summary = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "system_prompt": self.system_prompt,
            "summary": self.summary,
            "messages": self.messages,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MessageHistory":
        history = cls()
        history.system_prompt = data.get("system_prompt")
        history.summary = data.get("summary")
        history.messages = data.get("messages", [])
        return history
