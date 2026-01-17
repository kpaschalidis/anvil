from __future__ import annotations

import sys


def main() -> int:
    from anvil.cli import _main_fetch

    argv = sys.argv[1:]
    if argv and argv[0] == "dump":
        argv = argv[1:]

    print("Scout is deprecated. Use `anvil fetch ...` instead.", file=sys.stderr)
    return int(_main_fetch(argv) or 0)


if __name__ == "__main__":
    raise SystemExit(main())

