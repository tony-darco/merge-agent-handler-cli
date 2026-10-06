"""Auto-update check — at most once per hour, prints to stderr."""

from __future__ import annotations

import json
import time

import httpx

from merge_cli import __version__
from merge_cli.config import CONFIG_DIR, VERSION_CACHE_FILE
from merge_cli.output import warn

CHECK_INTERVAL = 3600  # 1 hour


def maybe_check_for_update() -> None:
    """Check PyPI for a newer version, at most once per hour. Non-blocking on failure."""
    try:
        cache = _load_cache()
        now = time.time()

        if now - cache.get("last_check", 0) < CHECK_INTERVAL:
            # Still within the check interval — just show cached warning if needed
            _warn_if_outdated(cache.get("latest_version"))
            return

        latest = _fetch_latest_version()
        _save_cache(latest, now)
        _warn_if_outdated(latest)
    except Exception:
        # Never let update check crash the CLI
        pass


def _load_cache() -> dict:
    try:
        return json.loads(VERSION_CACHE_FILE.read_text())
    except Exception:
        return {}


def _save_cache(latest_version: str, check_time: float) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    VERSION_CACHE_FILE.write_text(
        json.dumps({"latest_version": latest_version, "last_check": check_time}) + "\n"
    )


def _fetch_latest_version() -> str:
    resp = httpx.get("https://pypi.org/pypi/merge-api/json", timeout=5)
    resp.raise_for_status()
    return resp.json()["info"]["version"]


def _warn_if_outdated(latest: str | None) -> None:
    if latest and latest != __version__:
        warn(f"Update available: {__version__} → {latest}. Run: merge update")
