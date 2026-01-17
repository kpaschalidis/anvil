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
- [ ] Improve citation UX: per-claim numbered citations + short “why this source” snippet
- [ ] Sessions UX: list both fetch+research by default; add shortcuts to open fetch artifacts
- [ ] Align fetch sessions meta: optionally emit `meta.json` directly from FetchService (not only CLI)
- [ ] Docs: update `examples/` that still reference `scout` CLI (if any)
