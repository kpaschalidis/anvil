# TODO

## Completed
- [x] Unified CLI: single `anvil` entrypoint (no `scout` CLI)
- [x] Tavily `web_search` tool behind `search` extra (`tavily-python`)
- [x] Deep research workflow (orchestrator-workers) with strict grounding + citations
- [x] Research artifacts under `data/sessions/<session_id>/research/`
- [x] Fail-fast when Tavily/key missing (no silent fallback)
- [x] `anvil sessions` command for listing/opening session artifacts
- [x] Fetch resume via Scout `state.json` (plus unit test)
- [x] Research resume reruns (`anvil research --resume <id>`)

## Next
- [x] Deep research planning: fail-fast on invalid JSON (no silent fallback)
- [x] Deep research artifacts: persist `planner_raw.txt` + `planner_error.json` under session
- [x] Fix deep research empty-task fallback bug (`_to_worker_tasks` should never reference undefined `query`)
- [x] Tests: strict planning failure + best-effort fallback coverage
- [ ] Improve citation UX: per-claim numbered citations + grounded “why this source” snippet
- [x] Improve citation UX: per-claim numbered citations + grounded “why this source” snippet
- [x] Sessions UX: sessions list both kinds by default + shortcuts to open fetch artifacts
- [x] Fetch meta: allow FetchService to write/update `meta.json` (CLI not required)
- [x] Docs sweep: no references to removed `scout` CLI
- [x] Planning artifacts: include raw output on validation errors too
- [x] Research profiles: `quick` default, `deep` for 15–20m
- [x] Deep profile: pagination + min web_search calls enforced
- [x] Deep profile: round-2 gap-fill (orchestrator→workers→synthesis)
- [x] Replace per-worker min calls with coverage floors (domains/citations)
