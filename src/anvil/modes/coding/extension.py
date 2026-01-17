import subprocess

from anvil.git import GitRepo
from anvil.linter import Linter
from anvil.parser import ResponseParser


class CodingExtension:
    def __init__(self, runtime):
        self.runtime = runtime
        self.git = GitRepo(str(runtime.root_path))
        self.linter = Linter(str(runtime.root_path))
        self.parser = ResponseParser()
        self.last_commit_hash: str | None = None
        self.last_edited_files: list[str] = []
        self._fixing_lint: bool = False

    def on_files_changed(self, filepaths: list[str], source: str) -> None:
        self.last_edited_files.extend(filepaths)

    def on_assistant_message(self, content: str) -> None:
        if not content:
            return

        edits = self.parser.parse_edits(content)
        if edits:
            self._apply_edits(edits)
            if not self._fixing_lint:
                self._lint_and_fix()

    def _apply_edits(self, edits: list[tuple[str, str, str]]) -> None:
        print(f"\n📝 Applying {len(edits)} edit(s)...")

        edited_files: list[str] = []
        for filename, search, replace in edits:
            print(f"  Editing {filename}...")
            if self.runtime.config.dry_run:
                print(f"    [DRY RUN] Would edit {filename}")
                continue

            success = self.runtime.files.apply_edit(filename, search, replace)
            if success:
                print(f"  ✅ {filename} updated")
                edited_files.append(filename)
            else:
                print(f"  ❌ Failed to edit {filename}")

        if edited_files:
            self.runtime.hooks.fire_files_changed(edited_files, "apply_edits")

        if edited_files and self.runtime.config.auto_commit and not self.runtime.config.dry_run:
            self._auto_commit(edited_files)

    def _lint_and_fix(self) -> None:
        if not self.runtime.config.auto_lint or not self.last_edited_files:
            return
        if self._fixing_lint:
            return

        self._fixing_lint = True
        try:
            retries = self.runtime.config.lint_fix_retries
            files_to_lint = list(set(self.last_edited_files))
            self.last_edited_files.clear()

            last_errors: list[str] = []

            for attempt in range(retries):
                errors: list[str] = []
                for filepath in files_to_lint:
                    result = self.linter.lint(filepath)
                    if result:
                        errors.append(f"## {filepath}\n{result.text}")

                if not errors:
                    return

                last_errors = errors
                print(f"🔍 Lint errors found (attempt {attempt + 1}/{retries})")
                error_msg = "Fix these lint errors:\n\n" + "\n\n".join(errors)
                self.runtime.run_turn(error_msg)

                files_to_lint = list(set(self.last_edited_files))
                self.last_edited_files.clear()

            if last_errors:
                print("⚠️  Could not auto-fix all lint errors")

        finally:
            self._fixing_lint = False

    def _auto_commit(self, files: list[str]) -> None:
        try:
            commit_msg = "anvil: applied edits"
            hash_str, _ = self.git.commit(commit_msg, files)
            self.last_commit_hash = hash_str
            print("✅ Auto-committed changes")
        except Exception as e:
            print(f"⚠️  Failed to commit: {e}")

    def undo_last_commit(self) -> None:
        if not self.last_commit_hash:
            print("❌ No recent commit to undo")
            return
        try:
            subprocess.run(
                ["git", "reset", "--soft", "HEAD~1"],
                cwd=self.runtime.root_path,
                check=True,
                capture_output=True,
            )
            print(f"✅ Reverted commit {self.last_commit_hash[:8]}")
            self.last_commit_hash = None
        except subprocess.CalledProcessError as e:
            print(f"❌ Failed to undo: {e}")
