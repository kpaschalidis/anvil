- [x] Restructure prompt blocks into `src/anvil/prompts/blocks/`
- [x] Update prompt composer to load first-party blocks and include grep/skill tools
- [x] Add grep tool to runtime tool registry
- [x] Add skill tool to runtime tool registry
- [x] Remove legacy vendor prompt tree

- [x] Add `src/anvil/modes/` with `ModeConfig`, registry, and `coding` mode defaults
- [x] Make runtime mode-aware (apply defaults + namespace + optional tool registration)
- [x] Make prompt composer search across `prompt_block_dirs`
- [x] Namespace sessions under `.anvil/sessions/<namespace>/` with legacy fallback
- [x] Update CLI to accept `mode` argument without breaking file args
- [x] Update tests and run `uv run pytest -v`

- [x] Add runtime hooks (`RuntimeHooks`) and extensions dict
- [x] Move coding behaviors into `CodingExtension` via hooks
- [x] Move `git_status`, `git_diff`, `apply_edit` tools into coding mode
- [x] Move `/git` and `/undo` into coding mode (REPL wires `extend_builtins`)
- [x] Move tool prompts for coding tools into `src/anvil/modes/coding/prompts/`
- [x] Make `system.md` less coding-specific
- [x] Run `uv run pytest -v`
# Unified CLI + Fetch-only Scout (TODOs)

## Decisions (locked)
- Scout becomes fetch-only (remove extraction pipeline + prompts).
- Unified entrypoint remains `anvil` (keep `scout` as shim temporarily).

## Implementation checklist
- [ ] Introduce `common.events` + minimal event types used by services.
- [ ] Add `scout.services.fetch.FetchService` (fetch-only loop using `scout.sources.*` + `scout.storage.Storage.save_document`).
- [ ] Add `anvil fetch ...` command that calls `FetchService`.
- [ ] Deprecate `scout` CLI: keep `scout dump` working by delegating to `FetchService`, and print a deprecation notice for other commands.
- [ ] Remove Scout extraction surface: `scout run/export/watch/stats/tag/clone/archive` (or re-scope them to raw-doc sessions only).
- [ ] Delete extraction-only modules once unused: `src/scout/{agent,extract,filters,validation,complexity,pipeline,parallel,circuit_breaker,progress}.py` and `src/scout/prompts/`.
- [ ] Simplify `src/scout/config.py` and `src/scout/models.py` to raw-doc-only.
- [ ] Update docs: `README.md`, `SCOUT_QUICKSTART.md`, `CLI_EXAMPLES.md`.
- [ ] Update tests: remove/replace extraction-related tests; add tests for `FetchService`.
