# Config Reference

This repo exposes one CLI: `anvil`.

## `.env` / Environment variables

See `.env.example` for the full list. Common ones:

- `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `DEEPSEEK_API_KEY`: LLM provider keys (LiteLLM)
- `TAVILY_API_KEY`: required for `anvil research` (Tavily web search)
- `GITHUB_TOKEN` / `GH_TOKEN`: recommended for `github_issues` fetch source
- `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT`: required for `reddit` fetch source

## Extras

- `uv sync --extra dev`: tests/lint
- `uv sync --extra scout`: fetch sources (Reddit/PRAW, ProductHunt/Playwright)
- `uv sync --extra search`: deep research web search (Tavily)
- `uv sync --extra gui`: Gradio UI

