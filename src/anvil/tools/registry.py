from typing import Dict, Any, Callable, List


class ToolRegistry:
    def __init__(self):
        self.tools: Dict[str, Dict[str, Any]] = {}
        self.implementations: Dict[str, Callable] = {}

    def register_tool(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        implementation: Callable,
    ):
        self.tools[name] = {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters,
            },
        }

        self.implementations[name] = implementation

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        return list(self.tools.values())

    def execute_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        if name not in self.implementations:
            return {"error": f"Tool {name} not found"}

        try:
            result = self.implementations[name](**arguments)
            return {"success": True, "result": result}
        except Exception as e:
            return {"success": False, "error": str(e)}
