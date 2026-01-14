from anvil.runtime.builtins import BuiltinCommands
from anvil.runtime.router import InputRouter


class AnvilREPL:
    def __init__(self, runtime):
        self.runtime = runtime
        self.builtins = BuiltinCommands(runtime)
        if runtime.mode and runtime.mode.extend_builtins:
            runtime.mode.extend_builtins(self.builtins, runtime)
        self.router = InputRouter(self.builtins, runtime.markdown_index)

    def run(self, initial_message: str | None = None):
        print(f"🤖 Anvil started (model: {self.runtime.config.model})")
        print("Commands: /help for all commands")
        print()

        if initial_message:
            self.runtime.process_user_message(initial_message)

        while True:
            try:
                user_input = input("\n> ").strip()

                if not user_input:
                    continue

                route = self.router.route(user_input)
                if route.kind == "builtin":
                    if not self.builtins.handle(route.name, route.args):
                        break
                    continue
                if route.kind == "command":
                    entry = self.runtime.markdown_index.commands.get(route.name)
                    if entry:
                        self.runtime.markdown_executor.execute(entry, route.args)
                        continue
                if route.kind == "skill":
                    entry = self.runtime.markdown_index.skills.get(route.name)
                    if entry:
                        self.runtime.markdown_executor.execute(entry, route.args)
                        continue
                if route.kind == "unknown":
                    print(
                        f"Unknown command: /{route.name}. Type /help for available commands."
                    )
                    continue

                self.runtime.process_user_message(route.args)

            except KeyboardInterrupt:
                print("\n\n⚠️  Interrupted")
                self.runtime.interrupted = True
                break
            except EOFError:
                break
            except Exception as e:
                print(f"\n❌ Error: {e}")
                import traceback

                traceback.print_exc()
