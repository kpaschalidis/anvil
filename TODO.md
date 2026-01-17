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
- [ ] Phase 1–3 (v2): workers + agent facade + CLI subcommands
- [ ] Introduce `common.events` + minimal event types used by services.
- [ ] Add `scout.services.fetch.FetchService` (fetch-only loop using `scout.sources.*` + `scout.storage.Storage.save_document`).
- [ ] Add `anvil fetch ...` command that calls `FetchService`.
- [x] Add tool gating for workers (`allowed_tool_names`) in `SubagentRunner.run_task()`.
- [ ] Add `anvil/subagents/parallel.py` with `spawn_parallel()` (restricted tools by default).
- [ ] Add `anvil/agent/agent.py` facade over `AnvilRuntime` (workflow tools stubbed initially).
- [ ] Refactor `anvil/cli.py` to use argparse subcommands (`fetch`, `code`, legacy mode fallback).
- [ ] Deprecate `scout` CLI: keep `scout dump` working by delegating to `FetchService`, and print a deprecation notice for other commands.
- [ ] Remove Scout extraction surface: `scout run/export/watch/stats/tag/clone/archive` (or re-scope them to raw-doc sessions only).
- [ ] Delete extraction-only modules once unused: `src/scout/{agent,extract,filters,validation,complexity,pipeline,parallel,circuit_breaker,progress}.py` and `src/scout/prompts/`.
- [ ] Simplify `src/scout/config.py` and `src/scout/models.py` to raw-doc-only.
- [ ] Update docs: `README.md`, `SCOUT_QUICKSTART.md`, `CLI_EXAMPLES.md`.
- [ ] Update tests: remove/replace extraction-related tests; add tests for `FetchService`.

## Phase 4–6 (v2): Deep Research (Tavily) first
- [ ] Add optional dependency group `search` with `tavily-python`.
- [ ] Add tool `web_search` (Tavily) and register in runtime.
- [ ] Allow `web_search` in worker-safe tools by default.
- [ ] Implement `anvil/workflows/deep_research.py` (orchestrator-workers).
- [ ] Wire `anvil research "query"` CLI command to DeepResearchWorkflow.
- [ ] Wire `AnvilAgent` tool `deep_research` to DeepResearchWorkflow.
- [ ] Add tests for `web_search` and `DeepResearchWorkflow` (no network).
- [ ] Update docs for `uv sync --extra search` and new commands.

## Deep Research hardening (strict grounding + artifacts)
- [ ] Remove implicit URL scraping; only tool-trace citations count.
- [ ] Enforce per-worker invariants: `web_search_calls>=1` and `citations>=1` (else mark worker failed).
- [ ] Add strict modes:
  - [ ] Default: strict grounding (`min_total_citations` required; allow some worker failures).
  - [ ] `--strict-all`: fail if any worker fails.
  - [ ] `--best-effort`: allow partial output with explicit warnings.
- [ ] Persist artifacts in session dir:
  - [ ] `data/sessions/<session_id>/meta.json` (`kind="research"`, config, timestamps; no secrets).
  - [ ] `data/sessions/<session_id>/research/plan.json`.
  - [ ] `data/sessions/<session_id>/research/workers/<task_id>.json` (output + trace + citations).
  - [ ] `data/sessions/<session_id>/research/report.md`.
  - [ ] Always write artifacts even on failure.
- [ ] Make report citeable:
  - [ ] Synthesis returns structured JSON with claims + citation URLs.
  - [ ] Validate citations are subset of collected citations; downgrade or fail depending on strictness.
- [ ] CLI flags: `--session-id`, `--data-dir`, `--output`, `--no-save-artifacts`, `--min-citations`, `--strict-all`, `--best-effort`.
- [ ] Tests: strict grounding failure, artifact layout + redaction, claim→citation validation.
