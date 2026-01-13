from pathlib import Path
from typing import List, Optional, Set


IGNORED_DIRS: Set[str] = {
    ".venv",
    "venv",
    ".git",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".eggs",
    "*.egg-info",
}

MAX_FILES = 500


class FileManager:
    def __init__(self, root_path: str):
        self.root_path = Path(root_path)

    def read_file(self, filepath: str) -> str:
        full_path = self.root_path / filepath
        try:
            return full_path.read_text()
        except Exception as e:
            raise Exception(f"Error reading {filepath}: {str(e)}")

    def write_file(self, filepath: str, content: str):
        full_path = self.root_path / filepath
        try:
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content)
        except Exception as e:
            raise Exception(f"Error writing {filepath}: {str(e)}")

    def list_files(self, pattern: str = "*") -> List[str]:
        files = []
        for path in self.root_path.rglob(pattern):
            if not path.is_file():
                continue
            rel_path = path.relative_to(self.root_path)
            if self._should_ignore(rel_path):
                continue
            files.append(str(rel_path))
            if len(files) >= MAX_FILES:
                break
        return sorted(files)

    def _should_ignore(self, rel_path: Path) -> bool:
        parts = rel_path.parts
        for part in parts:
            if part in IGNORED_DIRS:
                return True
            if part.startswith(".") and part not in {".env", ".gitignore"}:
                return True
        return False

    def apply_edit(self, filepath: str, search: str, replace: str) -> bool:
        try:
            content = self.read_file(filepath)

            if search in content:
                new_content = content.replace(search, replace, 1)
                self.write_file(filepath, new_content)
                return True

            new_content = self._fuzzy_replace(content, search, replace)
            if new_content:
                self.write_file(filepath, new_content)
                return True

            return False

        except Exception as e:
            print(f"Error applying edit: {e}")
            return False

    def _fuzzy_replace(self, content: str, search: str, replace: str) -> Optional[str]:
        def normalize(text):
            return " ".join(text.split())

        search_norm = normalize(search)
        content_norm = normalize(content)

        search_start = content_norm.find(search_norm)
        if search_start == -1:
            return None

        orig_pos = 0
        norm_pos = 0

        for i, char in enumerate(content):
            if (
                content_norm[norm_pos : norm_pos + len(search_norm)] == search_norm
                and norm_pos == search_start
            ):
                start_pos = i
                break
            if not char.isspace():
                norm_pos += 1
        else:
            return None

        search_end = search_start + len(search_norm)
        norm_pos = search_start
        for i in range(start_pos, len(content)):
            if norm_pos >= search_end:
                end_pos = i
                break
            if not content[i].isspace():
                norm_pos += 1
        else:
            end_pos = len(content)

        return content[:start_pos] + replace + content[end_pos:]
