from __future__ import annotations

from importlib.metadata import entry_points


def load_source_classes() -> dict[str, type]:
    eps = entry_points()
    try:
        group = eps.select(group="scout.sources")
    except Exception:
        group = eps.get("scout.sources", [])

    classes: dict[str, type] = {}
    for ep in group:
        try:
            classes[ep.name] = ep.load()
        except Exception:
            continue
    return classes

