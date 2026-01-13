from anvil.parser import ResponseParser


class TestResponseParser:
    def test_parse_single_edit(self):
        response = """
Here's the fix:

test.py
```python
<<<<<<< SEARCH
def foo():
    return 1
=======
def foo():
    return 2
>>>>>>> REPLACE
```
"""
        edits = ResponseParser.parse_edits(response)
        
        assert len(edits) == 1
        filename, search, replace = edits[0]
        assert filename == "test.py"
        assert "return 1" in search
        assert "return 2" in replace

    def test_parse_no_edits(self):
        response = "No changes needed."
        edits = ResponseParser.parse_edits(response)
        
        assert len(edits) == 0
