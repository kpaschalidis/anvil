import re
import subprocess
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path


@dataclass
class LintResult:
    text: str
    lines: list[int]


class Linter:
    FATAL_FLAKE8_CODES = "E9,F821,F823,F831,F406,F407,F701,F702,F704,F706"

    def __init__(self, root: str):
        self.root = Path(root)

    def lint(self, filepath: str) -> LintResult | None:
        full_path = self.root / filepath
        if full_path.suffix != ".py":
            return None

        try:
            code = full_path.read_text()
        except OSError:
            return None

        compile_result = self._compile_check(code, filepath)
        flake8_result = self._flake8_check(filepath)

        return self._merge_results(compile_result, flake8_result)

    def _compile_check(self, code: str, filepath: str) -> LintResult | None:
        try:
            compile(code, filepath, "exec")
            return None
        except SyntaxError as err:
            lines = [err.lineno - 1] if err.lineno else []
            tb = traceback.format_exception(type(err), err, None)
            return LintResult(text="".join(tb), lines=lines)

    def _flake8_check(self, filepath: str) -> LintResult | None:
        cmd = [
            sys.executable,
            "-m",
            "flake8",
            f"--select={self.FATAL_FLAKE8_CODES}",
            "--show-source",
            "--isolated",
            filepath,
        ]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, cwd=self.root, timeout=30
            )
            if result.returncode == 0:
                return None
            errors = result.stdout + result.stderr
            lines = self._extract_line_numbers(errors, filepath)
            return LintResult(text=errors, lines=lines)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None

    def _extract_line_numbers(self, text: str, filepath: str) -> list[int]:
        pattern = rf"{re.escape(filepath)}:(\d+)"
        return [int(m) - 1 for m in re.findall(pattern, text)]

    def _merge_results(self, *results: LintResult | None) -> LintResult | None:
        texts, lines = [], set()
        for r in results:
            if r:
                texts.append(r.text)
                lines.update(r.lines)
        if not texts:
            return None
        return LintResult(text="\n".join(texts), lines=list(lines))
