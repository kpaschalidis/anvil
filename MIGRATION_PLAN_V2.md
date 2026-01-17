# Anvil Architecture Refactor v2 — Implementation Plan

This plan targets the “v2” outcome: incremental refactor, Scout owns `FetchService`, Anvil adds a facade agent + workflows, and Deep Research uses general web search (Tavily) with an orchestrator-workers pattern.

## Phase 4–6 (Current focus): Deep Research first

### Phase 4 — Web Search Tool (Tavily)
- [ ] Add optional dependency group `search` in `pyproject.toml` (e.g. `tavily-python`).
- [ ] Add `anvil` tool implementation `web_search` (Tavily-backed) with:
  - [ ] Env var support: `TAVILY_API_KEY`.
  - [ ] Pagination contract (page/page_size) implemented via “fetch more then slice”.
  - [ ] Deterministic structured return: `results[]`, `query`, `page`, `page_size`, `has_more`.
  - [ ] Graceful failure when dependency/key missing (structured error).
- [ ] Register `web_search` in `AnvilRuntime._register_tools()`.
- [ ] Add `web_search` to worker-safe tool allowlist.

### Phase 5 — DeepResearchWorkflow (Orchestrator-Workers)
- [ ] Add `anvil/workflows/deep_research.py`:
  - [ ] Orchestrator step: generate a JSON plan of worker tasks (no tools).
  - [ ] Worker step: `ParallelWorkerRunner.spawn_parallel()` with restricted tools by default (read-only + `web_search`).
  - [ ] Synthesis step: combine worker outputs into Markdown with citations (URLs).
  - [ ] Provide deterministic fallbacks when planning JSON parse fails.
- [ ] Add a small configuration dataclass for tuning (workers, timeouts, model).

### Phase 6 — Wiring + Tests + Docs
- [ ] Replace `AnvilAgent._tool_deep_research()` stub to call `DeepResearchWorkflow`.
- [ ] Update `anvil` CLI subcommand `research` to call `DeepResearchWorkflow` (argparse).
- [ ] Add unit tests:
  - [ ] `web_search` tool: missing dependency/key error; pagination slicing contract.
  - [ ] `DeepResearchWorkflow`: uses fake LLM + fake worker outputs (no network).
- [ ] Update docs:
  - [ ] `README.md` / `CLI_EXAMPLES.md`: `uv sync --extra search`, `anvil research "..."`.

## Deferred (Later): Need Finding pipeline
- [ ] Implement `ExtractService` (wrap `scout/extraction/*` and `scout/storage`).
- [ ] Implement `AnalyzeService` (deterministic + optional LLM).
- [ ] Implement `NeedFindingWorkflow` (fetch → extract → analyze → report).
- [ ] Wire into agent + CLI (`anvil need-finding ...`).

