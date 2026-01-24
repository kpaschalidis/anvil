from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class SessionMeta:
    session_id: str
    kind: str
    status: str
    created_at: str | None = None
    updated_at: str | None = None
    query: str | None = None
    topic: str | None = None
    model: str | None = None
    config: dict[str, Any] | None = None
    workers: dict[str, Any] | None = None
    citations: int | None = None
    error: str | None = None


def meta_path(*, data_dir: str, session_id: str) -> Path:
    return Path(data_dir) / session_id / "meta.json"


def load_meta(*, data_dir: str, session_id: str) -> dict[str, Any] | None:
    path = meta_path(data_dir=data_dir, session_id=session_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_meta(*, data_dir: str, session_id: str, meta: dict[str, Any]) -> Path:
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    meta = dict(meta or {})
    meta.setdefault("created_at", now)
    meta["updated_at"] = now
    path = meta_path(data_dir=data_dir, session_id=session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def list_session_ids(*, data_dir: str) -> list[str]:
    base = Path(data_dir)
    if not base.exists():
        return []
    out: list[str] = []
    for p in base.iterdir():
        if p.is_dir():
            out.append(p.name)
    return out


def list_sessions(*, data_dir: str, kind: str | None = None) -> list[dict[str, Any]]:
    sessions: list[dict[str, Any]] = []
    for sid in list_session_ids(data_dir=data_dir):
        meta = load_meta(data_dir=data_dir, session_id=sid)
        if not meta:
            continue
        if kind and meta.get("kind") != kind:
            continue
        meta = dict(meta)
        meta.setdefault("session_id", sid)
        sessions.append(meta)

    def _key(m: dict[str, Any]) -> str:
        return str(m.get("updated_at") or m.get("created_at") or "")

    sessions.sort(key=_key, reverse=True)
    return sessions
