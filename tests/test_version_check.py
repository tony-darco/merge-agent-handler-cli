"""Tests for version check mechanism."""

from __future__ import annotations

import json
import time

from merge_cli.version_check import (
    CHECK_INTERVAL,
    _load_cache,
    _save_cache,
    _warn_if_outdated,
    maybe_check_for_update,
)


def test_warn_if_outdated_shows_message(capsys, monkeypatch):
    monkeypatch.setattr("merge_cli.version_check.__version__", "0.1.0")
    _warn_if_outdated("0.2.0")
    captured = capsys.readouterr()
    assert "Update available" in captured.err
    assert "0.2.0" in captured.err


def test_warn_if_outdated_silent_when_current(capsys, monkeypatch):
    monkeypatch.setattr("merge_cli.version_check.__version__", "0.1.0")
    _warn_if_outdated("0.1.0")
    captured = capsys.readouterr()
    assert captured.err == ""


def test_warn_if_outdated_silent_when_none(capsys):
    _warn_if_outdated(None)
    captured = capsys.readouterr()
    assert captured.err == ""


def test_save_and_load_cache(tmp_path, monkeypatch):
    monkeypatch.setattr("merge_cli.version_check.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("merge_cli.version_check.VERSION_CACHE_FILE", tmp_path / "cache.json")

    now = time.time()
    _save_cache("0.2.0", now)

    cache = _load_cache()
    assert cache["latest_version"] == "0.2.0"
    assert cache["last_check"] == now


def test_load_cache_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr("merge_cli.version_check.VERSION_CACHE_FILE", tmp_path / "missing.json")
    cache = _load_cache()
    assert cache == {}


def test_maybe_check_skips_within_interval(tmp_path, monkeypatch):
    cache_file = tmp_path / "cache.json"
    monkeypatch.setattr("merge_cli.version_check.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("merge_cli.version_check.VERSION_CACHE_FILE", cache_file)
    monkeypatch.setattr("merge_cli.version_check.__version__", "0.1.0")

    # Write a recent cache
    cache_file.write_text(json.dumps({"latest_version": "0.1.0", "last_check": time.time()}))

    # Should not make any HTTP requests — just check cache
    maybe_check_for_update()
    # No error = passed (no network call needed)


def test_maybe_check_fetches_when_stale(tmp_path, monkeypatch, httpx_mock):
    cache_file = tmp_path / "cache.json"
    monkeypatch.setattr("merge_cli.version_check.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("merge_cli.version_check.VERSION_CACHE_FILE", cache_file)
    monkeypatch.setattr("merge_cli.version_check.__version__", "0.1.0")

    # Write an expired cache
    cache_file.write_text(
        json.dumps(
            {
                "latest_version": "0.1.0",
                "last_check": time.time() - CHECK_INTERVAL - 1,
            }
        )
    )

    httpx_mock.add_response(
        url="https://pypi.org/pypi/merge-api/json",
        json={"info": {"version": "0.2.0"}},
    )

    maybe_check_for_update()

    # Cache should be updated
    cache = json.loads(cache_file.read_text())
    assert cache["latest_version"] == "0.2.0"


def test_maybe_check_never_crashes(monkeypatch):
    """Update check should never crash the CLI, even on exceptions."""
    monkeypatch.setattr(
        "merge_cli.version_check._load_cache",
        lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    # Should not raise
    maybe_check_for_update()
