"""Profile loading for the AI3D pipeline (standard library only).

A profile is JSON. config/default.json is always loaded first; a user file
passed with --config is merged on top, then --set overrides are applied.
Keys starting with "_" are comments and ignored.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROFILE = REPO_ROOT / "config" / "default.json"


def _strip_comments(value):
    if isinstance(value, dict):
        return {k: _strip_comments(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, list):
        return [_strip_comments(v) for v in value]
    return value


def merge(base: dict, override: dict) -> dict:
    """Recursively merge override into a copy of base. Unknown keys are rejected."""
    out = copy.deepcopy(base)
    for key, value in override.items():
        if key not in out:
            raise ValueError(f"Unknown config key: {key}")
        if isinstance(out[key], dict):
            if not isinstance(value, dict):
                raise ValueError(f"Config key {key} must be an object")
            out[key] = merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _parse_scalar(text: str):
    try:
        return json.loads(text)
    except ValueError:
        return text


def apply_override(config: dict, assignment: str) -> dict:
    """Apply one "section.key=value" override (value parsed as JSON when possible)."""
    if "=" not in assignment:
        raise ValueError(f"--set expects section.key=value, got: {assignment}")
    dotted, raw = assignment.split("=", 1)
    keys = [k for k in dotted.strip().split(".") if k]
    if not keys:
        raise ValueError(f"--set has an empty key: {assignment}")
    nested: dict = {}
    cursor = nested
    for key in keys[:-1]:
        cursor[key] = {}
        cursor = cursor[key]
    cursor[keys[-1]] = _parse_scalar(raw.strip())
    return merge(config, nested)


def load_profile(path: Path | None = None, overrides: list[str] | None = None) -> dict:
    config = _strip_comments(json.loads(DEFAULT_PROFILE.read_text()))
    if path is not None:
        user = _strip_comments(json.loads(Path(path).expanduser().read_text()))
        config = merge(config, user)
    for assignment in overrides or []:
        config = apply_override(config, assignment)
    return config


def repo_path(value: str | Path) -> Path:
    """Resolve a config path: ~ expands, relative paths are relative to the repo."""
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path.resolve()
