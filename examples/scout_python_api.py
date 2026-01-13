#!/usr/bin/env python3
"""
Scout Agent - Python API Examples

This shows how to use Scout programmatically instead of via CLI.
Useful for integrating Scout into other tools or workflows.
"""

import os
from pathlib import Path

from scout.config import ScoutConfig
from scout.session import SessionManager, SessionState
from scout.agent import IngestionAgent
from scout.sources.hackernews import HackerNewsSource
from scout.storage import Storage
from scout.progress import ProgressInfo


def example_basic_research():
    """Example 1: Basic research session"""
    print("=== Example 1: Basic Research ===\n")

    # Configure
    config = ScoutConfig.from_profile("quick")
    config.max_cost_usd = 0.50  # Set budget

    # Create session
    manager = SessionManager(config.data_dir)
    session = manager.create_session(topic="AI code editors", max_iterations=20)

    print(f"Session ID: {session.session_id}")
    print(f"Topic: {session.topic}\n")

    # Initialize source
    source = HackerNewsSource(config.hackernews)

    # Progress callback
    def on_progress(info: ProgressInfo):
        pct = (info.iteration / info.max_iterations) * 100
        print(
            f"\r[{pct:3.0f}%] Docs: {info.docs_collected} | "
            f"Snippets: {info.snippets_extracted} | "
            f"Cost: ${info.total_cost_usd:.4f}",
            end="",
            flush=True,
        )

    # Run agent
    agent = IngestionAgent(
        session=session, sources=[source], config=config, on_progress=on_progress
    )

    try:
        agent.run()
        print("\n\n✅ Research complete!")
        print(f"Documents collected: {session.stats.docs_collected}")
        print(f"Snippets extracted: {session.stats.snippets_extracted}")
        print(f"Total cost: ${session.stats.total_cost_usd:.4f}")
        return session.session_id
    except KeyboardInterrupt:
        print("\n⏸️  Session paused. Resume with the session ID above.")
        return session.session_id


def example_query_results(session_id: str):
    """Example 2: Query extracted results"""
    print(f"\n=== Example 2: Query Results ===\n")

    data_dir = os.environ.get("SCOUT_DATA_DIR", "data/sessions")
    storage = Storage(session_id, data_dir)

    # Get all snippets
    snippets = list(storage.get_all_snippets())

    print(f"Total snippets: {len(snippets)}\n")

    # Filter high-confidence, high-intensity snippets
    important = [s for s in snippets if s.confidence >= 0.8 and s.intensity >= 4]

    print(f"High-priority pain points ({len(important)}):\n")
    for i, snippet in enumerate(important[:5], 1):
        print(f"{i}. [{snippet.signal_type}] {snippet.pain_statement}")
        print(
            f"   Confidence: {snippet.confidence:.2f}, Intensity: {snippet.intensity}/5"
        )
        print(f"   Excerpt: {snippet.excerpt[:100]}...")
        print()

    # Count by signal type
    from collections import Counter

    signal_counts = Counter(s.signal_type for s in snippets)

    print("\nSignal type distribution:")
    for signal_type, count in signal_counts.most_common():
        print(f"  {signal_type}: {count}")

    # Top entities
    entity_counts = Counter()
    for snippet in snippets:
        entity_counts.update(snippet.entities)

    print("\nTop entities mentioned:")
    for entity, count in entity_counts.most_common(10):
        print(f"  {entity}: {count}")


def example_resume_session(session_id: str):
    """Example 3: Resume a paused session"""
    print(f"\n=== Example 3: Resume Session ===\n")

    data_dir = os.environ.get("SCOUT_DATA_DIR", "data/sessions")
    manager = SessionManager(data_dir)

    # Load existing session
    session = manager.load_session(session_id)
    if not session:
        print(f"❌ Session {session_id} not found")
        return

    print(f"Resuming session: {session_id}")
    print(f"Topic: {session.topic}")
    print(f"Current status: {session.status}")
    print(f"Documents: {session.stats.docs_collected}")
    print(f"Snippets: {session.stats.snippets_extracted}")
    print(f"Tasks remaining: {len(session.task_queue)}\n")

    # Continue with more iterations
    config = ScoutConfig.from_profile("standard")
    config.max_iterations = 60  # Allow more iterations

    source = HackerNewsSource(config.hackernews)
    agent = IngestionAgent(session, [source], config)

    try:
        agent.run()
        print("\n✅ Session complete!")
    except KeyboardInterrupt:
        print("\n⏸️  Session paused again")


def example_custom_config():
    """Example 4: Custom configuration"""
    print("\n=== Example 4: Custom Configuration ===\n")

    from scout.filters import FilterConfig
    from scout.validation import SnippetValidationConfig

    config = ScoutConfig(
        max_iterations=30,
        max_documents=100,
        max_cost_usd=1.0,
        parallel_workers=8,
        saturation_threshold=0.15,  # Lower = more exhaustive
        filter=FilterConfig(
            min_content_length=200,  # Skip short posts
            min_score=10,  # Skip low-scoring posts
            skip_deleted_authors=True,
        ),
        snippet_validation=SnippetValidationConfig(
            min_confidence=0.6,  # Higher quality threshold
            min_excerpt_length=20,
            min_pain_statement_length=20,
        ),
    )

    print("Custom configuration:")
    print(f"  Max iterations: {config.max_iterations}")
    print(f"  Max documents: {config.max_documents}")
    print(f"  Budget: ${config.max_cost_usd}")
    print(f"  Parallel workers: {config.parallel_workers}")
    print(f"  Min content length: {config.filter.min_content_length}")
    print(f"  Min snippet confidence: {config.snippet_validation.min_confidence}")
    print()

    # Use this config for research...
    # session = manager.create_session(...)
    # agent = IngestionAgent(session, sources, config)


def example_export_results(session_id: str):
    """Example 5: Export results programmatically"""
    print(f"\n=== Example 5: Export Results ===\n")

    data_dir = os.environ.get("SCOUT_DATA_DIR", "data/sessions")
    storage = Storage(session_id, data_dir)

    # Export to CSV
    output_dir = Path(f"/tmp/scout_export_{session_id}")
    output_dir.mkdir(exist_ok=True)

    csv_path = storage.export_csv(output_dir / "snippets.csv")
    print(f"✅ Exported CSV: {csv_path}")

    # Export markdown summary
    manager = SessionManager(data_dir)
    session = manager.load_session(session_id)
    if session:
        md_path = storage.export_markdown_summary(output_dir / "report.md", session)
        print(f"✅ Exported Markdown: {md_path}")

    # Export JSONL (default format)
    files = storage.export_jsonl(output_dir)
    print("\n✅ Exported JSONL:")
    for name, path in files.items():
        if path.exists():
            print(f"  - {name}: {path}")


def main():
    """Run examples"""
    print("Scout Agent - Python API Examples")
    print("=" * 50)
    print()

    # Check API key
    if not os.getenv("OPENAI_API_KEY") and not os.getenv("ANTHROPIC_API_KEY"):
        print("❌ Error: No LLM API key found")
        print("Set OPENAI_API_KEY or ANTHROPIC_API_KEY")
        return

    print("Which example would you like to run?\n")
    print("1. Basic research session (quick, ~$0.10)")
    print("2. Query existing results")
    print("3. Resume a paused session")
    print("4. Show custom configuration")
    print("5. Export results")
    print()

    choice = input("Enter choice (1-5) or 'all' to run sequentially: ").strip()

    if choice == "1" or choice == "all":
        session_id = example_basic_research()
        if choice == "all" and session_id:
            example_query_results(session_id)
            example_export_results(session_id)

    elif choice == "2":
        session_id = input("Enter session ID: ").strip()
        example_query_results(session_id)

    elif choice == "3":
        session_id = input("Enter session ID to resume: ").strip()
        example_resume_session(session_id)

    elif choice == "4":
        example_custom_config()

    elif choice == "5":
        session_id = input("Enter session ID: ").strip()
        example_export_results(session_id)

    else:
        print("Invalid choice")


if __name__ == "__main__":
    main()
