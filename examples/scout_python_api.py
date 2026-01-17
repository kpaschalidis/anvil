from __future__ import annotations

"""
Fetch-only Python API example (Scout sources via FetchService).

Requires:
  uv sync --extra scout
"""

from scout.config import ScoutConfig
from scout.services.fetch import FetchConfig, FetchService


def main() -> None:
    config = ScoutConfig.from_profile("quick", sources=["hackernews"])
    config.validate(sources=["hackernews"])

    service = FetchService(
        FetchConfig(
            topic="AI note taking",
            sources=["hackernews"],
            max_documents=25,
        )
    )
    result = service.run(scout_config=config)
    print("session_id:", result.session_id)
    print("documents_fetched:", result.documents_fetched)


if __name__ == "__main__":
    main()

