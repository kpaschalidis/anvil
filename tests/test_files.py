import pytest
from anvil.files import FileManager


class TestFileManager:
    def test_read_file(self, tmp_path):
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello world")

        fm = FileManager(str(tmp_path))
        content = fm.read_file("test.txt")

        assert content == "hello world"

    def test_write_file(self, tmp_path):
        fm = FileManager(str(tmp_path))
        fm.write_file("new_file.txt", "new content")

        assert (tmp_path / "new_file.txt").read_text() == "new content"

    def test_write_file_creates_directories(self, tmp_path):
        fm = FileManager(str(tmp_path))
        fm.write_file("nested/dir/file.txt", "nested content")

        assert (tmp_path / "nested/dir/file.txt").read_text() == "nested content"

    def test_list_files(self, tmp_path):
        (tmp_path / "a.py").write_text("")
        (tmp_path / "b.py").write_text("")
        (tmp_path / "c.txt").write_text("")

        fm = FileManager(str(tmp_path))
        py_files = fm.list_files("*.py")

        assert len(py_files) == 2
        assert "a.py" in py_files
        assert "b.py" in py_files

    def test_apply_edit_exact_match(self, tmp_path):
        test_file = tmp_path / "test.py"
        test_file.write_text("def foo():\n    return 1")

        fm = FileManager(str(tmp_path))
        result = fm.apply_edit("test.py", "return 1", "return 2")

        assert result is True
        assert "return 2" in test_file.read_text()

    def test_apply_edit_not_found(self, tmp_path):
        test_file = tmp_path / "test.py"
        test_file.write_text("def foo():\n    return 1")

        fm = FileManager(str(tmp_path))
        result = fm.apply_edit("test.py", "nonexistent", "replacement")

        assert result is False
