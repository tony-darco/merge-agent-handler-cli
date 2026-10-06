"""Tests for merge setup host detection and write safety."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from merge_cli.commands.setup import detect_host, setup


@pytest.fixture(autouse=True)
def _clear_host_env(monkeypatch):
    monkeypatch.delenv("CLAUDECODE", raising=False)
    monkeypatch.delenv("CURSOR_TRACE_ID", raising=False)


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({"CLAUDECODE": "1"}, "claude-code"),
        ({"CURSOR_TRACE_ID": "trace"}, "cursor"),
        ({"CLAUDECODE": "1", "CURSOR_TRACE_ID": "trace"}, "claude-code"),
        ({}, "agents-md"),
    ],
)
def test_detect_host(monkeypatch, env, expected):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert detect_host() == expected


def test_setup_without_target_uses_detected_host(tmp_path, monkeypatch):
    monkeypatch.setenv("CURSOR_TRACE_ID", "trace")
    result = CliRunner().invoke(setup, ["--project-dir", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "Detected host: cursor" in result.output
    assert (tmp_path / ".cursorrules").exists()
    assert not (tmp_path / "CLAUDE.md").exists()


def test_setup_explicit_target_ignores_env(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    result = CliRunner().invoke(setup, ["agents-md", "--project-dir", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "Detected host" not in result.output
    assert "merge authenticate <connector>" in (tmp_path / "AGENTS.md").read_text()


def test_setup_skips_malformed_settings_json(tmp_path):
    settings_file = tmp_path / ".claude" / "settings.json"
    settings_file.parent.mkdir()
    settings_file.write_text("{not json")

    result = CliRunner().invoke(setup, ["claude-code", "--project-dir", str(tmp_path)])

    assert result.exit_code == 0, result.output
    # The malformed file is left untouched instead of being replaced.
    assert settings_file.read_text() == "{not json"


def test_setup_updates_valid_settings_json(tmp_path):
    settings_file = tmp_path / ".claude" / "settings.json"
    settings_file.parent.mkdir()
    settings_file.write_text(json.dumps({"permissions": {"allow": ["Bash(ls *)"]}}))

    result = CliRunner().invoke(setup, ["claude-code", "--project-dir", str(tmp_path)])

    assert result.exit_code == 0, result.output
    allow = json.loads(settings_file.read_text())["permissions"]["allow"]
    assert allow == ["Bash(ls *)", "Bash(merge *)"]


def test_setup_skips_symlinked_targets(tmp_path):
    real = tmp_path / "elsewhere.md"
    real.write_text("original")
    (tmp_path / "AGENTS.md").symlink_to(real)

    result = CliRunner().invoke(setup, ["agents-md", "--project-dir", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert real.read_text() == "original"
