"""User defaults stored in ``config.json`` next to the session log."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Optional

CONFIG_NAME = "config.json"

DEFAULTS: dict[str, Any] = {
    "work": 25,
    "short": 5,
    "long": 15,
    "cycles": 4,
    "bell": True,
    "notify": False,
    "color": "auto",
    "todo_file": "",  # path to a todo.txt for `start --task N`; empty = not set
    "tally": False,  # bump a pomodoros:N tag on the --task line per completed block
    "weekly_goal": 0,  # focus minutes per Monday-to-Sunday week; 0 = no goal
    "sound": "",  # WAV file played instead of the terminal bell; empty = bell
}

# key -> (kind, minimum, maximum)
_RANGES: dict[str, tuple[str, float, float]] = {
    "work": ("number", 1, 180),
    "short": ("number", 1, 60),
    "long": ("number", 1, 120),
    "cycles": ("int", 1, 12),
    "weekly_goal": ("int", 0, 10080),  # 10080 = every minute of a week
}
COLOR_MODES = ("auto", "always", "never")
_TRUE = {"true", "yes", "on", "1"}
_FALSE = {"false", "no", "off", "0"}


class ConfigError(ValueError):
    """An unknown key or an out-of-range / malformed value."""


def keys() -> list[str]:
    return list(DEFAULTS)


def _num(value: float) -> Any:
    return int(value) if float(value).is_integer() else float(value)


def validate(key: str, value: Any) -> Any:
    """Return ``value`` converted to the right type for ``key`` or raise ConfigError.

    Accepts both strings (from the command line) and JSON values.
    """
    if key not in DEFAULTS:
        raise ConfigError(f"unknown key {key!r} (known: {', '.join(DEFAULTS)})")
    if key in _RANGES:
        kind, low, high = _RANGES[key]
        if isinstance(value, bool):
            raise ConfigError(f"{key} must be a number")
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ConfigError(f"{key} must be a number, got {value!r}") from None
        if number != number:
            raise ConfigError(f"{key} must be a number, got {value!r}")
        if kind == "int" and not number.is_integer():
            raise ConfigError(f"{key} must be a whole number, got {value!r}")
        if not low <= number <= high:
            raise ConfigError(f"{key} must be between {_num(low)} and {_num(high)}, got {value}")
        return int(number) if kind == "int" else _num(number)
    if key in ("bell", "notify", "tally"):
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in _TRUE:
            return True
        if text in _FALSE:
            return False
        raise ConfigError(f"{key} must be true or false, got {value!r}")
    if key == "color":
        text = str(value).strip().lower()
        if text not in COLOR_MODES:
            raise ConfigError(f"color must be one of {', '.join(COLOR_MODES)}, got {value!r}")
        return text
    if key in ("todo_file", "sound"):
        if not isinstance(value, str):
            raise ConfigError(f"{key} must be a path, got {value!r}")
        text = value.strip()
        if any(ch in text for ch in "\r\n\0"):
            raise ConfigError(f"{key} must be a single-line path")
        return text
    raise ConfigError(f"unknown key {key!r}")  # pragma: no cover


def load(path: Path, warn: Optional[Callable[[str], None]] = None) -> dict[str, Any]:
    """Defaults overlaid with valid values from ``path``; bad entries are warned about."""
    cfg = dict(DEFAULTS)
    if not path.exists():
        return cfg
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        if warn:
            warn(f"ignoring unreadable config {path}: {exc}")
        return cfg
    if not isinstance(raw, dict):
        if warn:
            warn(f"ignoring config {path}: expected a JSON object")
        return cfg
    for key, value in raw.items():
        try:
            cfg[key] = validate(key, value)
        except ConfigError as exc:
            if warn:
                warn(f"ignoring config entry: {exc}")
    return cfg


def save_value(path: Path, key: str, value: Any) -> Any:
    """Validate and persist one key; returns the stored value."""
    clean = validate(key, value)
    current: dict[str, Any] = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(loaded, dict):
                current = {k: v for k, v in loaded.items() if k in DEFAULTS}
        except (OSError, ValueError):
            current = {}
    current[key] = clean
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8", newline="\n")
    tmp.replace(path)
    return clean
