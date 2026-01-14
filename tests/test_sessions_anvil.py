from pathlib import Path

from anvil.history import MessageHistory
from anvil.sessions.manager import SessionManager


def test_session_create_save_load(tmp_path: Path):
    manager = SessionManager(
        tmp_path,
        model="gpt-4o",
        system_prompt_hash="hash",
        system_prompt_version="v1",
    )

    history = MessageHistory()
    history.add_user_message("hello")
    history.add_assistant_message("world")

    manager.save_current(history)

    session_id = manager.current.metadata.id
    session_path = tmp_path / ".anvil" / "sessions" / "default" / f"{session_id}.json"
    assert session_path.exists()

    loaded = manager.load_session(session_id)
    assert loaded is not None
    assert loaded.messages == history.messages
