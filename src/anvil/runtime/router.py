from dataclasses import dataclass


@dataclass(frozen=True)
class RouteResult:
    kind: str
    name: str | None
    args: str


class InputRouter:
    def __init__(self, builtins, markdown_index):
        self.builtins = builtins
        self.markdown_index = markdown_index

    def route(self, user_input: str) -> RouteResult:
        if not user_input.startswith("/"):
            return RouteResult(kind="prompt", name=None, args=user_input)

        parts = user_input.split(maxsplit=1)
        cmd = parts[0].lstrip("/")
        args = parts[1] if len(parts) > 1 else ""

        if self.builtins.has_command(cmd):
            return RouteResult(kind="builtin", name=cmd, args=args)

        if cmd in self.markdown_index.commands:
            return RouteResult(kind="command", name=cmd, args=args)

        if cmd in self.markdown_index.skills:
            return RouteResult(kind="skill", name=cmd, args=args)

        return RouteResult(kind="unknown", name=cmd, args=args)
