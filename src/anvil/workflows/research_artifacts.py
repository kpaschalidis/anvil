from __future__ import annotations

import json
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any


def _json_default(obj: Any):
    if is_dataclass(obj):
        return asdict(obj)
    raise TypeError(f"Not JSON serializable: {type(obj)}")


def make_research_session_dir(*, data_dir: str, session_id: str) -> Path:
    session_dir = Path(data_dir) / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "research").mkdir(parents=True, exist_ok=True)
    (session_dir / "research" / "workers").mkdir(parents=True, exist_ok=True)
    return session_dir


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, default=_json_default, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def utc_ts() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

