"""JSON output formatting with agent-optimized hints. Warnings go to stderr."""

from __future__ import annotations

import json
import sys


def emit(data: dict) -> None:
    """Write JSON to stdout (for agent consumption)."""
    print(json.dumps(data, indent=2))


def warn(msg: str) -> None:
    """Write a warning to stderr (never contaminates JSON stdout)."""
    print(f"[merge] {msg}", file=sys.stderr)


def error_response(
    message: str,
    *,
    error_type: str = "error",
    hint: str | None = None,
) -> dict:
    return {
        "result": None,
        "status": "error",
        "error_type": error_type,
        "message": message,
        "hint": hint or message,
    }


def config_error(errors: list[str]) -> dict:
    return error_response(
        "; ".join(errors),
        error_type="config_error",
        hint="Run `merge agent signup` (agents) or `merge login` (humans) to set up credentials.",
    )
