import subprocess
from pathlib import Path
from typing import List, Tuple


class GitRepo:
    def __init__(self, root_path: str):
        self.root_path = Path(root_path)
        self._ensure_git_repo()

    def _ensure_git_repo(self):
        try:
            subprocess.run(
                ["git", "rev-parse", "--git-dir"],
                cwd=self.root_path,
                capture_output=True,
                check=True,
            )
        except subprocess.CalledProcessError:
            raise Exception("Not a git repository")

    def commit(self, message: str, files: List[str]) -> Tuple[str, str]:
        try:
            for file in files:
                subprocess.run(["git", "add", file], cwd=self.root_path, check=True)

            subprocess.run(
                ["git", "commit", "-m", message],
                cwd=self.root_path,
                capture_output=True,
                text=True,
                check=True,
            )

            hash_result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=self.root_path,
                capture_output=True,
                text=True,
                check=True,
            )

            return (hash_result.stdout.strip(), message)

        except subprocess.CalledProcessError as e:
            raise Exception(f"Git commit failed: {e.stderr}")

    def get_diff(self) -> str:
        result = subprocess.run(
            ["git", "diff"], cwd=self.root_path, capture_output=True, text=True
        )
        return result.stdout

    def get_status(self) -> str:
        result = subprocess.run(
            ["git", "status", "--short"],
            cwd=self.root_path,
            capture_output=True,
            text=True,
        )
        return result.stdout
