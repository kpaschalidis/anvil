from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from common.ids import generate_id
from common.jsonio import atomic_write_json, load_json
from anvil.sessions.schema import SessionMetadata, SessionState


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SessionManager:
    def __init__(
        self,
        root_path: str | Path,
        model: str,
        system_prompt_hash: str,
        system_prompt_version: str,
        namespace: str = "default",
    ):
        self.root_path = Path(root_path)
        self.namespace = namespace
        self.legacy_sessions_dir = self.root_path / ".anvil" / "sessions"
        self.sessions_dir = self.legacy_sessions_dir / namespace
        self.system_prompt_hash = system_prompt_hash
        self.system_prompt_version = system_prompt_version
        self.current: SessionState = self._create_session(model=model)
        self.save_current(messages=[])

    def _create_session(self, model: str, title: str | None = None) -> SessionState:
        now = _now_iso()
        metadata = SessionMetadata(
            id=generate_id(),
            title=title,
            created_at=now,
            updated_at=now,
            model=model,
        )
        return SessionState(
            metadata=metadata,
            system_prompt_hash=self.system_prompt_hash,
            system_prompt_version=self.system_prompt_version,
            messages=[],
        )

    def new_session(self, model: str, title: str | None = None) -> SessionState:
        self.current = self._create_session(model=model, title=title)
        self.save_current(messages=[])
        return self.current

    def save_current(self, history=None, title: str | None = None, messages=None) -> None:
        if title is not None:
            self.current.metadata.title = title
        self.current.metadata.updated_at = _now_iso()
        if messages is not None:
            self.current.messages = list(messages)
        elif history is not None:
            self.current.messages = list(history.messages)

        path = self.sessions_dir / f"{self.current.metadata.id}.json"
        atomic_write_json(path, self.current.model_dump())

    def load_session(self, session_id: str) -> SessionState | None:
        primary = self.sessions_dir / f"{session_id}.json"
        data = load_json(primary)
        if not data and self.namespace == "default":
            legacy = self.legacy_sessions_dir / f"{session_id}.json"
            data = load_json(legacy)
        if not data:
            return None
        session = SessionState.model_validate(data)
        self.current = session
        self.system_prompt_hash = session.system_prompt_hash
        self.system_prompt_version = session.system_prompt_version
        return session

    def list_sessions(self) -> list[dict[str, Any]]:
        sessions = []
        if self.sessions_dir.exists():
            for path in self.sessions_dir.glob("*.json"):
                data = load_json(path)
                if data:
                    sessions.append(data)

        if self.namespace == "default" and self.legacy_sessions_dir.exists():
            for path in self.legacy_sessions_dir.glob("*.json"):
                data = load_json(path)
                if data:
                    sessions.append(data)

        return sorted(
            sessions,
            key=lambda item: item.get("metadata", {}).get("updated_at", ""),
            reverse=True,
        )
