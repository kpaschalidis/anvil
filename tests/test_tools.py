from anvil.tools import ToolRegistry


class TestToolRegistry:
    def test_register_and_execute_tool(self):
        registry = ToolRegistry()
        
        def add(a: int, b: int) -> int:
            return a + b
        
        registry.register_tool(
            name="add",
            description="Add two numbers",
            parameters={
                "type": "object",
                "properties": {
                    "a": {"type": "integer"},
                    "b": {"type": "integer"},
                },
                "required": ["a", "b"],
            },
            implementation=add,
        )
        
        result = registry.execute_tool("add", {"a": 2, "b": 3})
        
        assert result["success"]
        assert result["result"] == 5

    def test_get_tool_schemas(self):
        registry = ToolRegistry()
        
        registry.register_tool(
            name="test",
            description="Test tool",
            parameters={"type": "object", "properties": {}},
            implementation=lambda: None,
        )
        
        schemas = registry.get_tool_schemas()
        
        assert len(schemas) == 1
        assert schemas[0]["function"]["name"] == "test"

    def test_execute_unknown_tool(self):
        registry = ToolRegistry()
        
        result = registry.execute_tool("unknown", {})
        
        assert "error" in result
