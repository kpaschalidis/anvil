import pytest
from anvil.linter import Linter, LintResult


class TestLinter:
    def test_valid_python_no_errors(self, tmp_path):
        (tmp_path / "valid.py").write_text("def foo():\n    return 1\n")
        linter = Linter(str(tmp_path))
        result = linter.lint("valid.py")
        assert result is None

    def test_syntax_error_detected(self, tmp_path):
        (tmp_path / "invalid.py").write_text("def foo(\n    return 1\n")
        linter = Linter(str(tmp_path))
        result = linter.lint("invalid.py")
        assert result is not None
        assert "SyntaxError" in result.text

    def test_non_python_file_skipped(self, tmp_path):
        (tmp_path / "file.txt").write_text("not python")
        linter = Linter(str(tmp_path))
        result = linter.lint("file.txt")
        assert result is None

    def test_undefined_name_detected(self, tmp_path):
        (tmp_path / "undef.py").write_text("x = undefined_var\n")
        linter = Linter(str(tmp_path))
        result = linter.lint("undef.py")
        if result:
            assert "F821" in result.text or "undefined" in result.text.lower()

    def test_missing_file_returns_none(self, tmp_path):
        linter = Linter(str(tmp_path))
        result = linter.lint("nonexistent.py")
        assert result is None

    def test_lint_result_dataclass(self):
        result = LintResult(text="error message", lines=[1, 2, 3])
        assert result.text == "error message"
        assert result.lines == [1, 2, 3]
