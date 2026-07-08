"""Lightweight key-value store for global calendar settings (e.g. default
required_staff per slot). Persisted as JSON at data/calendar_settings.json."""

from __future__ import annotations

import json
from pathlib import Path


DEFAULTS: dict = {
    "default_required_staff": 1,
}


def load_calendar_settings(path: Path) -> dict:
    if not path.exists() or path.stat().st_size == 0:
        return dict(DEFAULTS)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return dict(DEFAULTS)
    except (ValueError, OSError):
        return dict(DEFAULTS)
    return {**DEFAULTS, **data}


def save_calendar_settings(path: Path, settings: dict) -> None:
    out = {**DEFAULTS, **settings}
    out["default_required_staff"] = max(1, int(out.get("default_required_staff", 1) or 1))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")


def default_required_staff(path: Path = Path("data/calendar_settings.json")) -> int:
    return max(1, int(load_calendar_settings(path).get("default_required_staff", 1) or 1))
