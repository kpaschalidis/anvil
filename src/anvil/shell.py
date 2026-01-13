import subprocess
from pathlib import Path
from typing import Dict, Any


class ShellRunner:
    def __init__(self, root_path: str, auto_approve: bool = False):
        self.root_path = Path(root_path)
        self.auto_approve = auto_approve

    def run_command(self, command: str) -> Dict[str, Any]:
        if not self.auto_approve:
            print(f"\n🔧 Command to run: {command}")
            response = input("Execute? (y/n): ")
            if response.lower() != "y":
                return {
                    "success": False,
                    "error": "User cancelled",
                    "stdout": "",
                    "stderr": "",
                    "exit_code": -1,
                }

        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=self.root_path,
                capture_output=True,
                text=True,
                timeout=30,
            )

            return {
                "success": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "exit_code": result.returncode,
            }

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": "Command timed out",
                "stdout": "",
                "stderr": "",
                "exit_code": -1,
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "stdout": "",
                "stderr": "",
                "exit_code": -1,
            }
