from __future__ import annotations

import subprocess

try:
    import gradio as gr
except ImportError:
    gr = None


def _check_gradio() -> None:
    if gr is None:
        raise ImportError("Gradio not installed. Run: uv pip install 'anvil[gui]'")


def _get_root_path() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return "."


def _chat_handler(
    message: str,
    history,
    model: str,
) -> str:
    from anvil.agent.agent import AnvilAgent
    from anvil.config import AgentConfig, resolve_model_alias

    root_path = _get_root_path()
    config = AgentConfig(model=resolve_model_alias(model), stream=False)
    agent = AnvilAgent(root_path, config)

    return agent.execute(message)


def _fetch_handler(
    topic: str,
    sources: list[str],
    max_documents: int,
) -> str:
    if not topic.strip():
        return "Error: Topic is required"
    if not sources:
        return "Error: Select at least one source"

    from common.events import DocumentEvent, ErrorEvent, ProgressEvent
    from scout.config import ScoutConfig
    from scout.services.fetch import FetchConfig, FetchService

    logs: list[str] = []

    def on_event(event) -> None:
        if isinstance(event, ProgressEvent) and event.stage == "fetch":
            logs.append(f"[{event.current}/{event.total or '?'}] {event.message}")
        elif isinstance(event, DocumentEvent):
            pass
        elif isinstance(event, ErrorEvent):
            logs.append(f"Error: {event.message}")

    try:
        scout_config = ScoutConfig.from_profile("quick", sources=list(sources))
        scout_config.validate(sources=list(sources))
    except Exception as e:
        return f"Config error: {e}"

    service = FetchService(
        FetchConfig(
            topic=topic,
            sources=list(sources),
            max_documents=max_documents,
        ),
        on_event=on_event,
    )
    result = service.run(scout_config=scout_config)

    summary = [
        f"Session: {result.session_id}",
        f"Documents: {result.documents_fetched}",
        f"Duration: {result.duration_seconds:.1f}s",
    ]
    if result.errors:
        summary.append(f"Errors: {len(result.errors)}")

    return "\n".join(summary + ["", "--- Log ---"] + logs[-20:])


def create_app() -> "gr.Blocks":
    _check_gradio()

    with gr.Blocks(title="Anvil") as app:
        gr.Markdown("# Anvil")

        with gr.Tabs():
            with gr.Tab("Chat"):
                model_dropdown = gr.Dropdown(
                    choices=["gpt-4o", "sonnet", "opus", "haiku", "flash", "deepseek"],
                    value="gpt-4o",
                    label="Model",
                )
                gr.ChatInterface(
                    fn=_chat_handler,
                    additional_inputs=[model_dropdown],
                    examples=[
                        ["What files are in this project?"],
                        ["Explain the architecture of this codebase"],
                    ],
                )

            with gr.Tab("Fetch"):
                with gr.Row():
                    with gr.Column(scale=2):
                        fetch_topic = gr.Textbox(label="Topic", placeholder="insurance broker CRM")
                        fetch_sources = gr.CheckboxGroup(
                            choices=["hackernews", "reddit", "producthunt", "github_issues"],
                            value=["hackernews"],
                            label="Sources",
                        )
                        fetch_max = gr.Slider(minimum=10, maximum=200, value=50, step=10, label="Max Documents")
                        fetch_btn = gr.Button("Fetch", variant="primary")
                    with gr.Column(scale=3):
                        fetch_output = gr.Textbox(label="Result", lines=15, interactive=False)

                fetch_btn.click(
                    fn=_fetch_handler,
                    inputs=[fetch_topic, fetch_sources, fetch_max],
                    outputs=fetch_output,
                )

    return app


def launch(**kwargs) -> None:
    app = create_app()
    app.launch(**kwargs)
