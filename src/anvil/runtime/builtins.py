from anvil.config import resolve_model_alias


class BuiltinCommands:
    def __init__(self, runtime):
        self.runtime = runtime
        self._handlers = {
            "quit": self.cmd_quit,
            "exit": self.cmd_quit,
            "add": self.cmd_add,
            "drop": self.cmd_drop,
            "files": self.cmd_files,
            "clear": self.cmd_clear,
            "model": self.cmd_model,
            "tokens": self.cmd_tokens,
            "help": self.cmd_help,
            "commands": self.cmd_commands,
            "skills": self.cmd_skills,
            "reload": self.cmd_reload,
            "sessions": self.cmd_sessions,
            "load": self.cmd_load,
            "save": self.cmd_save,
        }

    def register(self, name: str, handler) -> None:
        self._handlers[name] = handler

    def unregister(self, name: str) -> None:
        self._handlers.pop(name, None)

    def list_commands(self) -> list[str]:
        return sorted(self._handlers.keys())

    def has_command(self, name: str) -> bool:
        return name in self._handlers

    def handle(self, name: str, args: str) -> bool:
        handler = self._handlers.get(name)
        if not handler:
            return True
        return handler(args)

    def cmd_quit(self, args: str) -> bool:
        print("👋 Goodbye!")
        return False

    def cmd_add(self, args: str) -> bool:
        if args:
            self.runtime.add_file_to_context(args)
        else:
            print("Usage: /add <filepath>")
        return True

    def cmd_drop(self, args: str) -> bool:
        if not args:
            print("Usage: /drop <filepath>")
            return True
        if args in self.runtime.files_in_context:
            self.runtime.files_in_context.remove(args)
            print(f"✅ Dropped {args} from context")
        else:
            print(f"❌ {args} not in context")
        return True

    def cmd_files(self, args: str) -> bool:
        if not self.runtime.files_in_context:
            print("No files in context")
        else:
            print("Files in context:")
            for path in self.runtime.files_in_context:
                print(f"  • {path}")
        return True

    def cmd_clear(self, args: str) -> bool:
        self.runtime.history.clear()
        self.runtime.files_in_context.clear()
        self.runtime._set_system_prompt()
        print("✅ Cleared chat history and context")
        return True

    def cmd_model(self, args: str) -> bool:
        if not args:
            print(f"Current model: {self.runtime.config.model}")
            return True
        self.runtime.config.model = resolve_model_alias(args)
        self.runtime._set_system_prompt()
        if getattr(self.runtime, "session_manager", None):
            self.runtime.session_manager.current.metadata.model = (
                self.runtime.config.model
            )
        if getattr(self.runtime, "subagent_runner", None):
            self.runtime.subagent_runner.default_model = self.runtime.config.model
        print(f"✅ Switched to model: {self.runtime.config.model}")
        return True

    def cmd_tokens(self, args: str) -> bool:
        try:
            import tiktoken

            enc = tiktoken.encoding_for_model("gpt-4o")
            messages = self.runtime.history.get_messages_for_api()
            total = sum(len(enc.encode(str(m.get("content", "")))) for m in messages)
            print(f"📊 Estimated tokens: ~{total:,}")
        except ImportError:
            msg_count = len(self.runtime.history.messages)
            print(
                f"📊 Messages in history: {msg_count} (install tiktoken for token count)"
            )
        return True

    def cmd_commands(self, args: str) -> bool:
        if not self.runtime.markdown_index.commands:
            print("No markdown commands found")
            return True
        print("Markdown commands:")
        for name in sorted(self.runtime.markdown_index.commands.keys()):
            print(f"  /{name}")
        return True

    def cmd_skills(self, args: str) -> bool:
        if not self.runtime.markdown_index.skills:
            print("No markdown skills found")
            return True
        print("Markdown skills:")
        for name in sorted(self.runtime.markdown_index.skills.keys()):
            print(f"  /{name}")
        return True

    def cmd_reload(self, args: str) -> bool:
        self.runtime.reload_extensions()
        print("✅ Reloaded .anvil commands, skills, and agents")
        return True

    def cmd_sessions(self, args: str) -> bool:
        manager = getattr(self.runtime, "session_manager", None)
        if not manager:
            print("Sessions not available")
            return True
        sessions = manager.list_sessions()
        if not sessions:
            print("No saved sessions")
            return True
        print("Sessions:")
        for entry in sessions:
            meta = entry.get("metadata", {})
            title = meta.get("title") or "untitled"
            print(f"  • {meta.get('id')} - {title}")
        return True

    def cmd_load(self, args: str) -> bool:
        if not args:
            print("Usage: /load <id>")
            return True
        manager = getattr(self.runtime, "session_manager", None)
        if not manager:
            print("Sessions not available")
            return True
        session = manager.load_session(args)
        if not session:
            print(f"❌ Session {args} not found")
            return True
        self.runtime.history.messages = list(session.messages)
        print(f"✅ Loaded session {args}")
        return True

    def cmd_save(self, args: str) -> bool:
        manager = getattr(self.runtime, "session_manager", None)
        if not manager:
            print("Sessions not available")
            return True
        title = args.strip() or None
        manager.save_current(self.runtime.history, title=title)
        print("✅ Session saved")
        return True

    def cmd_help(self, args: str) -> bool:
        print("\nCommands:")
        for name in self.list_commands():
            print(f"  /{name}")
        print()
        return True
