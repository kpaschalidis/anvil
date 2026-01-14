def extend_coding_builtins(builtins, runtime) -> None:
    ext = runtime.extensions["coding"]

    def cmd_undo(args: str) -> bool:
        ext.undo_last_commit()
        return True

    def cmd_git(args: str) -> bool:
        if args == "status":
            print(ext.git.get_status() or "Nothing to commit")
        elif args == "diff":
            print(ext.git.get_diff() or "No changes")
        else:
            print("Usage: /git status or /git diff")
        return True

    builtins.register("undo", cmd_undo)
    builtins.register("git", cmd_git)
