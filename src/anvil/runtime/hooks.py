from dataclasses import dataclass, field
from typing import Any, Callable, List


@dataclass
class RuntimeHooks:
    on_files_changed: List[Callable[[List[str], str], None]] = field(default_factory=list)
    on_assistant_message: List[Callable[[str], None]] = field(default_factory=list)
    on_tool_result: List[Callable[[str, str, Any], None]] = field(default_factory=list)
    on_turn_end: List[Callable[[], None]] = field(default_factory=list)

    def fire_files_changed(self, filepaths: List[str], source: str) -> None:
        for hook in list(self.on_files_changed):
            hook(filepaths, source)

    def fire_assistant_message(self, content: str) -> None:
        for hook in list(self.on_assistant_message):
            hook(content)

    def fire_tool_result(self, tool_name: str, tool_call_id: str, result: Any) -> None:
        for hook in list(self.on_tool_result):
            hook(tool_name, tool_call_id, result)

    def fire_turn_end(self) -> None:
        for hook in list(self.on_turn_end):
            hook()
