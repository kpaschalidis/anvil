import logging
from pathlib import Path
from datetime import datetime

from scout.models import SessionState, SearchTask, SessionStats, generate_id, utc_now
from scout.storage import atomic_write_json, load_json

logger = logging.getLogger(__name__)


class SessionError(Exception):
    pass


class SessionManager:
    def __init__(self, data_dir: str = "data/sessions"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def create_session(self, topic: str, max_iterations: int = 60) -> SessionState:
        session_id = generate_id()
        session = SessionState(
            session_id=session_id,
            topic=topic,
            status="running",
            max_iterations=max_iterations,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        self._save_state(session)
        logger.info(f"Created new session {session_id} for topic '{topic}'")
        return session

    def load_session(self, session_id: str) -> SessionState | None:
        state_path = self._state_path(session_id)
        data = load_json(state_path)
        if data is None:
            logger.warning(f"Session {session_id} not found")
            return None

        try:
            task_queue = [SearchTask(**t) for t in data.get("task_queue", [])]
            stats = SessionStats(**data.get("stats", {}))
            
            session = SessionState(
                session_id=data["session_id"],
                topic=data["topic"],
                status=data.get("status", "running"),
                extraction_prompt_version=data.get("extraction_prompt_version", "v1"),
                task_queue=task_queue,
                visited_tasks=data.get("visited_tasks", []),
                visited_docs=data.get("visited_docs", []),
                knowledge=data.get("knowledge", []),
                novelty_history=data.get("novelty_history", []),
                cursors=data.get("cursors", {}),
                stats=stats,
                complexity=data.get("complexity"),
                max_iterations=data.get("max_iterations", 60),
                created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else utc_now(),
                updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else utc_now(),
            )
            logger.info(f"Loaded session {session_id}: status={session.status}, tasks={len(session.task_queue)}")
            return session
        except (KeyError, TypeError, ValueError) as e:
            logger.error(f"Failed to parse session {session_id}: {e}")
            raise SessionError(f"Invalid session data: {e}") from e

    def save_session(self, session: SessionState) -> None:
        session.updated_at = utc_now()
        self._save_state(session)
        logger.debug(f"Saved session {session.session_id}")

    def _save_state(self, session: SessionState) -> None:
        state_path = self._state_path(session.session_id)
        data = {
            "session_id": session.session_id,
            "topic": session.topic,
            "status": session.status,
            "extraction_prompt_version": session.extraction_prompt_version,
            "task_queue": [t.model_dump(mode="json") for t in session.task_queue],
            "visited_tasks": session.visited_tasks,
            "visited_docs": session.visited_docs,
            "knowledge": session.knowledge[-100:],
            "novelty_history": session.novelty_history[-50:],
            "cursors": session.cursors,
            "stats": session.stats.model_dump(),
            "complexity": session.complexity,
            "max_iterations": session.max_iterations,
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
        }
        atomic_write_json(state_path, data)

    def _state_path(self, session_id: str) -> Path:
        session_dir = self.data_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        return session_dir / "state.json"

    def list_sessions(self) -> list[dict]:
        sessions = []
        if not self.data_dir.exists():
            return sessions

        for session_dir in self.data_dir.iterdir():
            if session_dir.is_dir():
                state_path = session_dir / "state.json"
                if state_path.exists():
                    data = load_json(state_path)
                    if data:
                        sessions.append({
                            "session_id": data.get("session_id"),
                            "topic": data.get("topic"),
                            "status": data.get("status"),
                            "created_at": data.get("created_at"),
                            "updated_at": data.get("updated_at"),
                            "stats": data.get("stats", {}),
                        })

        sessions.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
        return sessions

    def delete_session(self, session_id: str) -> bool:
        session_dir = self.data_dir / session_id
        if not session_dir.exists():
            return False

        import shutil
        shutil.rmtree(session_dir)
        logger.info(f"Deleted session {session_id}")
        return True


def load_or_create_session(
    session_id: str | None,
    topic: str | None,
    max_iterations: int,
    data_dir: str,
) -> SessionState:
    manager = SessionManager(data_dir)

    if session_id:
        session = manager.load_session(session_id)
        if session is None:
            raise SessionError(f"Session {session_id} not found")
        if session.status == "completed":
            raise SessionError(f"Session {session_id} is already completed")
        session.status = "running"
        return session

    if not topic:
        raise SessionError("Either session_id or topic must be provided")

    return manager.create_session(topic, max_iterations)
